#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import signal
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from statistics import fmean
from typing import Any


RE_INIT_TIME = re.compile(r"\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_EXEC_TIME = re.compile(r"\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_ROUTING = re.compile(r"\bRouting algorithm\s*:\s*([^\s]+)\b", re.I)
RE_INIT_MEM = re.compile(r"\bInitialization\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_EXEC_MEM = re.compile(r"\bExecution\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_HOST_NUMBER = re.compile(r"\bHost\s+number:\s*([0-9]+)\b", re.I)
RE_PROFILE_KV = re.compile(r"([A-Za-z0-9_]+)=([^=\s]+)")


FIELDS = [
    "case_id",
    "topology",
    "scale_name",
    "scale_value",
    "routing",
    "repeat",
    "rc",
    "init_time_s",
    "init_mem_gb",
    "route_mem_gb",
    "exec_time_s",
    "exec_mem_gb",
    "wall_s",
    "hosts",
    "threads",
    "traffic_pattern",
    "data_size",
    "allreduce_group_size",
    "allreduce_placement",
    "allreduce_step_gap",
    "config",
    "log",
    "cmd",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_csv_ints(text: str) -> list[int]:
    values = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not values:
        raise SystemExit("empty scale list")
    return values


def parse_csv_text(text: str) -> list[str]:
    values = [part.strip() for part in text.split(",") if part.strip()]
    if not values:
        raise SystemExit("empty routing list")
    return values


def pick_ns3_tool(root: Path) -> Path:
    for name in ("ns3", "ns", "waf"):
        candidate = root / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit(f"cannot find ./ns3, ./ns, or ./waf under {root}")


def pick_constructor_binary(root: Path, build_profile: str) -> Path | None:
    ex_dir = root / "build/src/datacenter/examples"
    if not ex_dir.exists():
        return None
    for candidate in sorted(ex_dir.glob(f"*constructor*{build_profile}*")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def process_tree_rss_kb(root_pid: int) -> int:
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            ppid = 0
            vmrss = 0
            with open(entry / "status", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("PPid:"):
                        ppid = int(line.split()[1])
                    elif line.startswith("VmRSS:"):
                        vmrss = int(line.split()[1])
            children.setdefault(ppid, []).append(pid)
            rss[pid] = vmrss
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue

    total = 0
    stack = [root_pid]
    seen: set[int] = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total


def run_logged(
    cmd: list[str],
    cwd: Path,
    log_path: Path,
    *,
    sample_memory: bool = False,
    sample_interval_s: float = 0.2,
) -> tuple[int, float, str, dict[str, int]]:
    ensure_dir(log_path.parent)
    start = time.time()
    output: list[str] = []
    peaks = {"init_peak_kb": 0, "total_peak_kb": 0}
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("$ " + shlex.join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        phase = {"name": "init", "stop": False}

        def sampler() -> None:
            while not phase["stop"]:
                rss_kb = process_tree_rss_kb(proc.pid)
                peaks["total_peak_kb"] = max(peaks["total_peak_kb"], rss_kb)
                if phase["name"] == "init":
                    peaks["init_peak_kb"] = max(peaks["init_peak_kb"], rss_kb)
                time.sleep(sample_interval_s)

        sampler_thread = None
        if sample_memory:
            sampler_thread = threading.Thread(target=sampler, daemon=True)
            sampler_thread.start()

        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)

        def forward_signal(signum: int, _frame: Any) -> None:
            phase["stop"] = True
            try:
                os.killpg(proc.pid, signum)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, forward_signal)
        signal.signal(signal.SIGINT, forward_signal)

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                output.append(line)
                if RE_INIT_TIME.search(line):
                    phase["name"] = "exec"
            rc = proc.wait()
        finally:
            phase["stop"] = True
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
            if sampler_thread is not None:
                sampler_thread.join(timeout=1.0)
        wall_s = time.time() - start
        log.write(f"\n[rc={rc} wall_s={wall_s:.6f}]\n")
    return rc, wall_s, "".join(output), peaks


def configure_and_build(root: Path, ns3_tool: Path, build_profile: str) -> None:
    log_path = root / "results" / f"build-topology-ring-allreduce-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    if ns3_tool.name in {"ns3", "ns"}:
        cfg = [str(ns3_tool), "configure", f"--build-profile={build_profile}", "--enable-examples"]
        rc, _, _, _ = run_logged(cfg, root, log_path)
        if rc != 0:
            raise SystemExit(f"configure failed; see {log_path}")
        rc, _, _, _ = run_logged([str(ns3_tool), "build", "constructor"], root, log_path)
        if rc != 0:
            raise SystemExit(f"build failed; see {log_path}")
    else:
        cfg = [str(ns3_tool), "configure", f"--build-profile={build_profile}", "--enable-examples"]
        rc, _, _, _ = run_logged(cfg, root, log_path)
        if rc != 0:
            raise SystemExit(f"waf configure failed; see {log_path}")
        rc, _, _, _ = run_logged([str(ns3_tool), "build"], root, log_path)
        if rc != 0:
            raise SystemExit(f"waf build failed; see {log_path}")


def load_generator(root: Path) -> Any:
    generator_dir = root / "src/datacenter/examples/inputs"
    if str(generator_dir) not in sys.path:
        sys.path.insert(0, str(generator_dir))
    from topology_generator import TopologyGenerator  # type: ignore

    return TopologyGenerator()


def torus_3d_levels(d: int) -> list[dict[str, Any]]:
    return [
        {
            "dims": [
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
            ]
        }
    ]


def write_config(generator: Any, topology: str, scale: int, out_dir: Path, bandwidth: str, delay: str) -> Path:
    ensure_dir(out_dir)
    if topology == "fattree":
        k = scale
        config = generator.generate(
            "fattree",
            k=k,
            bandwidth=bandwidth,
            delay=delay,
            routing="RuleBased",
        )
        path = out_dir / f"fattree_k{k}_{bandwidth}_{delay}.json"
    elif topology == "dragonfly":
        h = scale
        a = 2 * h
        p = h
        g = a * h + 1
        config = generator.generate(
            "dragonfly",
            groups=g,
            routers_per_group=a,
            hosts_per_router=p,
            global_links_per_router=h,
            global_link_arrangement="Absolute",
            bandwidth=bandwidth,
            delay=delay,
            routing="RuleBased",
        )
        path = out_dir / f"dragonfly_h{h}_g{g}_a{a}_p{p}_{bandwidth}_{delay}.json"
    elif topology == "torus":
        d = scale
        config = generator.generate(
            "custom",
            levels=torus_3d_levels(d),
            bandwidth=bandwidth,
            delay=delay,
            routing="RuleBased",
        )
        path = out_dir / f"torus3d_d{d}_{bandwidth}_{delay}.json"
    else:
        raise SystemExit(f"unsupported topology: {topology}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    return path


def parse_metrics(output: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if match := RE_INIT_TIME.search(output):
        metrics["init_time_s"] = float(match.group(1))
    if match := RE_EXEC_TIME.search(output):
        metrics["exec_time_s"] = float(match.group(1))
    if match := RE_ROUTING.search(output):
        metrics["routing"] = match.group(1)
    if match := RE_INIT_MEM.search(output):
        metrics["init_mem_kb"] = int(match.group(1))
    if match := RE_EXEC_MEM.search(output):
        metrics["exec_mem_kb"] = int(match.group(1))
    if match := RE_HOST_NUMBER.search(output):
        metrics["hosts"] = int(match.group(1))

    for line in output.splitlines():
        if "Initialization memory profile:" not in line:
            continue
        payload = line.split("Initialization memory profile:", 1)[1]
        fields = {key: value for key, value in RE_PROFILE_KV.findall(payload)}
        if fields.get("stage") != "routing_state":
            continue
        try:
            metrics["route_mem_kb"] = int(float(fields.get("delta", "")))
        except ValueError:
            pass
    return metrics


def gb_from_kb(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value) / (1024.0 * 1024.0):.6f}"


def metric_value(metrics: dict[str, Any], key: str) -> str:
    value = metrics.get(key)
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def run_case(
    root: Path,
    ns3_tool: Path,
    constructor_bin: Path | None,
    *,
    topology: str,
    scale_name: str,
    scale: int,
    routing: str,
    repeat: int,
    threads: int,
    config_path: Path,
    traffic_pattern: str,
    data_size: int,
    degree: int,
    allreduce_group_size: int,
    allreduce_placement: str,
    allreduce_step_gap: float,
    profile: bool,
    log_dir: Path,
) -> dict[str, str]:
    case_id = f"{topology}_{scale_name}{scale}_{routing}_ds{data_size}_t{threads}_r{repeat}"
    log_path = log_dir / f"{case_id}.log"
    program = [
        f"--config={config_path}",
        f"--routing={routing}",
        f"--trafficPattern={traffic_pattern}",
        f"--dataSize={data_size}",
        f"--degree={degree}",
        f"--memory={'true' if profile else 'false'}",
    ]
    if traffic_pattern == "grouped-allreduce":
        program.extend([
            f"--allreduceGroupSize={allreduce_group_size}",
            f"--allreducePlacement={allreduce_placement}",
            f"--allreduceStepGap={allreduce_step_gap}",
        ])
    if constructor_bin is not None:
        cmd = [str(constructor_bin)] + program
    else:
        cmd = [str(ns3_tool), "run", "constructor " + " ".join(program), "--no-build"]

    rc, wall_s, output, peaks = run_logged(cmd, root, log_path, sample_memory=True)
    metrics = parse_metrics(output)
    init_mem_kb = metrics.get("init_mem_kb", peaks.get("init_peak_kb"))
    exec_mem_kb = metrics.get("exec_mem_kb", peaks.get("total_peak_kb"))
    routing_used = metrics.get("routing", routing)
    return {
        "case_id": case_id,
        "topology": topology,
        "scale_name": scale_name,
        "scale_value": str(scale),
        "routing": str(routing_used),
        "repeat": str(repeat),
        "rc": str(rc),
        "init_time_s": metric_value(metrics, "init_time_s"),
        "init_mem_gb": gb_from_kb(init_mem_kb),
        "route_mem_gb": gb_from_kb(metrics.get("route_mem_kb")),
        "exec_time_s": metric_value(metrics, "exec_time_s"),
        "exec_mem_gb": gb_from_kb(exec_mem_kb),
        "wall_s": f"{wall_s:.6f}",
        "hosts": metric_value(metrics, "hosts"),
        "threads": str(threads),
        "traffic_pattern": traffic_pattern,
        "data_size": str(data_size),
        "allreduce_group_size": str(allreduce_group_size) if traffic_pattern == "grouped-allreduce" else "",
        "allreduce_placement": allreduce_placement if traffic_pattern == "grouped-allreduce" else "",
        "allreduce_step_gap": f"{allreduce_step_gap:.9f}" if traffic_pattern == "grouped-allreduce" else "",
        "config": str(config_path),
        "log": str(log_path),
        "cmd": shlex.join(cmd),
    }


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    ensure_dir(path.parent)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    grouped: dict[tuple[str, str, str, str, str], dict[str, list[float]]] = {}
    for row in rows:
        if row["rc"] != "0":
            continue
        key = (row["topology"], row["scale_value"], row["routing"], row["threads"], row["data_size"])
        buckets = grouped.setdefault(key, {field: [] for field in FIELDS})
        for field in ["init_time_s", "init_mem_gb", "route_mem_gb", "exec_time_s", "exec_mem_gb", "wall_s", "hosts"]:
            if row[field] != "":
                buckets[field].append(float(row[field]))

    out_rows: list[dict[str, str]] = []
    for (topology, scale, routing, threads, data_size), buckets in sorted(grouped.items(), key=lambda item: (int(item[0][1]), item[0][2], int(item[0][3]), int(item[0][4]))):
        scale_name = {"fattree": "k", "dragonfly": "h", "torus": "d"}[topology]
        out_rows.append({
            "topology": topology,
            "scale_name": scale_name,
            "scale_value": scale,
            "routing": routing,
            "threads": threads,
            "data_size": data_size,
            "init_time_s": f"{fmean(buckets['init_time_s']):.6f}" if buckets["init_time_s"] else "",
            "init_mem_gb": f"{fmean(buckets['init_mem_gb']):.6f}" if buckets["init_mem_gb"] else "",
            "route_mem_gb": f"{fmean(buckets['route_mem_gb']):.6f}" if buckets["route_mem_gb"] else "",
            "exec_time_s": f"{fmean(buckets['exec_time_s']):.6f}" if buckets["exec_time_s"] else "",
            "exec_mem_gb": f"{fmean(buckets['exec_mem_gb']):.6f}" if buckets["exec_mem_gb"] else "",
            "wall_s": f"{fmean(buckets['wall_s']):.6f}" if buckets["wall_s"] else "",
            "hosts": f"{fmean(buckets['hosts']):.0f}" if buckets["hosts"] else "",
            "repeat_count": str(len(buckets["wall_s"])),
        })

    fields = [
        "topology",
        "scale_name",
        "scale_value",
        "routing",
        "threads",
        "data_size",
        "init_time_s",
        "init_mem_gb",
        "route_mem_gb",
        "exec_time_s",
        "exec_mem_gb",
        "wall_s",
        "hosts",
        "repeat_count",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        return [
            {field: (row.get(field) or "") for field in reader.fieldnames}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]


def normalize_run_row(row: dict[str, str], default_data_size: str = "") -> dict[str, str]:
    normalized = {field: (row.get(field) or "") for field in FIELDS}
    if not normalized["data_size"] and default_data_size:
        normalized["data_size"] = default_data_size
    if not normalized["threads"]:
        normalized["threads"] = "1"
    return normalized


def synthesize_run_rows_from_summary(
    path: Path,
    *,
    topology: str,
    scale_name: str,
    traffic_pattern: str,
    data_size_values: list[int],
    allreduce_group_size: int,
    allreduce_placement: str,
    allreduce_step_gap: float,
) -> list[dict[str, str]]:
    rows = read_rows(path)
    if not rows:
        return []
    default_data_size = str(data_size_values[0]) if len(data_size_values) == 1 else ""
    synthesized: list[dict[str, str]] = []
    for row in rows:
        row_topology = row.get("topology") or topology
        if row_topology != topology:
            continue
        scale = row.get("scale_value") or ""
        routing = row.get("routing") or ""
        if not scale or not routing:
            continue
        data_size = row.get("data_size") or default_data_size
        if not data_size:
            continue
        threads = row.get("threads") or "1"
        try:
            repeat_count = max(1, int(float(row.get("repeat_count") or "1")))
        except ValueError:
            repeat_count = 1
        for repeat in range(1, repeat_count + 1):
            run_row = {field: "" for field in FIELDS}
            run_row.update({
                "case_id": f"{topology}_{scale_name}{scale}_{routing}_ds{data_size}_t{threads}_r{repeat}",
                "topology": topology,
                "scale_name": row.get("scale_name") or scale_name,
                "scale_value": scale,
                "routing": routing,
                "repeat": str(repeat),
                "rc": "0",
                "init_time_s": row.get("init_time_s") or "",
                "init_mem_gb": row.get("init_mem_gb") or "",
                "route_mem_gb": row.get("route_mem_gb") or "",
                "exec_time_s": row.get("exec_time_s") or "",
                "exec_mem_gb": row.get("exec_mem_gb") or "",
                "wall_s": row.get("wall_s") or "",
                "hosts": row.get("hosts") or "",
                "threads": threads,
                "traffic_pattern": traffic_pattern,
                "data_size": data_size,
                "allreduce_group_size": str(allreduce_group_size) if traffic_pattern == "grouped-allreduce" else "",
                "allreduce_placement": allreduce_placement if traffic_pattern == "grouped-allreduce" else "",
                "allreduce_step_gap": f"{allreduce_step_gap:.9f}" if traffic_pattern == "grouped-allreduce" else "",
            })
            synthesized.append(run_row)
    return synthesized


def case_key(
    topology: str,
    scale_name: str,
    scale: str | int,
    routing: str,
    data_size: str | int,
    threads: str | int,
    repeat: str | int,
) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(topology),
        str(scale_name),
        str(scale),
        str(routing),
        str(data_size),
        str(threads),
        str(repeat),
    )


def row_case_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str, str] | None:
    values = [
        row.get("topology", ""),
        row.get("scale_name", ""),
        row.get("scale_value", ""),
        row.get("routing", ""),
        row.get("data_size", ""),
        row.get("threads", ""),
        row.get("repeat", ""),
    ]
    if not all(values):
        return None
    return case_key(*values)


def completed_case_keys(rows: list[dict[str, str]], resume_policy: str) -> set[tuple[str, str, str, str, str, str, str]]:
    if resume_policy == "rerun_all":
        return set()
    completed: set[tuple[str, str, str, str, str, str, str]] = set()
    for row in rows:
        key = row_case_key(row)
        if key is None:
            continue
        if resume_policy == "skip_any":
            completed.add(key)
            continue
        try:
            rc = int((row.get("rc") or "").strip())
        except ValueError:
            rc = -1
        if rc == 0:
            completed.add(key)
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns3-root", required=True)
    parser.add_argument("--topology", choices=["fattree", "dragonfly", "torus"], required=True)
    parser.add_argument("--values", default="")
    parser.add_argument("--routings", default="NodeBfs,RuleBased")
    parser.add_argument(
        "--routing-values",
        action="append",
        default=[],
        help="Routing-specific scale list, e.g. Global:8,16,24. Can be repeated.",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--traffic-pattern", default="grouped-allreduce", choices=["allreduce", "grouped-allreduce", "alltoall", "flows"])
    parser.add_argument("--data-size", type=int, default=1048576)
    parser.add_argument(
        "--data-size-values",
        default="",
        help="Comma-separated data sizes in bytes. Defaults to the single --data-size value.",
    )
    parser.add_argument("--degree", type=int, default=4)
    parser.add_argument(
        "--threads",
        default="1",
        help="Constructor thread count. This runner is single-threaded and requires --threads=1.",
    )
    parser.add_argument("--allreduce-group-size", type=int, default=8)
    parser.add_argument("--allreduce-placement", default="strided", choices=["contiguous", "strided"])
    parser.add_argument("--allreduce-step-gap", type=float, default=0.0)
    parser.add_argument("--bandwidth", default="100Gbps")
    parser.add_argument("--delay", default="1us")
    parser.add_argument("--build-profile", default="optimized")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--resume-policy",
        default="skip_success",
        choices=["skip_success", "skip_any", "rerun_failed", "rerun_all"],
        help="Resume policy for existing run/stats CSVs: skip successful cases by default.",
    )
    parser.add_argument("--profile", action="store_true", help="Enable constructor --memory=true profiling output.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--stats-name", required=True, help="Output stats CSV name.")
    parser.add_argument("--runs-name", required=True, help="Output per-run CSV name.")
    args = parser.parse_args()

    root = Path(args.ns3_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    config_dir = out_dir / "configs"
    log_dir = out_dir / "logs"
    ensure_dir(out_dir)
    ensure_dir(log_dir)

    ns3_tool = pick_ns3_tool(root)
    thread_values = parse_csv_ints(args.threads)
    if any(value <= 0 for value in thread_values):
        raise SystemExit("--threads values must be positive")
    data_size_values = parse_csv_ints(args.data_size_values) if args.data_size_values else [args.data_size]
    if any(value <= 0 for value in data_size_values):
        raise SystemExit("--data-size and --data-size-values must be positive")
    if thread_values != [1]:
        raise SystemExit(
            "This topology Ring AllReduce runner is single-threaded. Use THREADS=1."
        )
    scale_name = {"fattree": "k", "dragonfly": "h", "torus": "d"}[args.topology]
    groups: list[tuple[str, list[int]]] = []
    if args.routing_values:
        for item in args.routing_values:
            if ":" not in item:
                raise SystemExit(f"invalid --routing-values entry: {item}")
            routing, values_text = item.split(":", 1)
            routing = routing.strip()
            if not routing:
                raise SystemExit(f"invalid --routing-values entry: {item}")
            groups.append((routing, parse_csv_ints(values_text)))
    else:
        if not args.values:
            raise SystemExit("--values is required unless --routing-values is used")
        values = parse_csv_ints(args.values)
        routings = parse_csv_text(args.routings)
        groups = [(routing, values) for routing in routings]

    stats_name = args.stats_name
    runs_name = args.runs_name
    default_data_size = str(data_size_values[0]) if len(data_size_values) == 1 else ""
    runs_path = out_dir / runs_name
    stats_path = out_dir / stats_name
    if args.resume_policy == "rerun_all":
        rows: list[dict[str, str]] = []
    elif runs_path.exists():
        rows = [normalize_run_row(row, default_data_size) for row in read_rows(runs_path)]
        if rows:
            print(f"[RESUME] loaded {len(rows)} existing run rows from {runs_path}")
    else:
        rows = synthesize_run_rows_from_summary(
            stats_path,
            topology=args.topology,
            scale_name=scale_name,
            traffic_pattern=args.traffic_pattern,
            data_size_values=data_size_values,
            allreduce_group_size=args.allreduce_group_size,
            allreduce_placement=args.allreduce_placement,
            allreduce_step_gap=args.allreduce_step_gap,
        )
        if rows:
            print(f"[RESUME] synthesized {len(rows)} completed run rows from {stats_path}")
    completed = completed_case_keys(rows, args.resume_policy)
    if completed:
        print(f"[RESUME] {len(completed)} cases will be skipped by policy={args.resume_policy}")

    cases = [
        (routing, scale, data_size, repeat, threads)
        for routing, values in groups
        for scale in values
        for data_size in data_size_values
        for repeat in range(1, args.repeats + 1)
        for threads in thread_values
    ]
    total = len(cases)
    pending = [
        case
        for case in cases
        if case_key(args.topology, scale_name, case[1], case[0], case[2], case[4], case[3]) not in completed
    ]
    if pending and not args.skip_build:
        configure_and_build(root, ns3_tool, args.build_profile)
    constructor_bin = pick_constructor_binary(root, args.build_profile) if pending else None
    generator = load_generator(root) if pending else None

    done = 0
    config_paths: dict[int, Path] = {}
    for routing, scale, data_size, repeat, threads in cases:
        done += 1
        current_key = case_key(args.topology, scale_name, scale, routing, data_size, threads, repeat)
        if current_key in completed:
            print(f"[{done}/{total}] SKIP {args.topology} {scale_name}={scale} routing={routing} data_size={data_size} repeat={repeat} threads={threads} (already complete)")
            continue
        assert generator is not None
        if scale not in config_paths:
            config_paths[scale] = write_config(generator, args.topology, scale, config_dir, args.bandwidth, args.delay)
        config_path = config_paths[scale]
        print(f"[{done}/{total}] {args.topology} {scale_name}={scale} routing={routing} data_size={data_size} repeat={repeat} threads={threads}")
        row = run_case(
            root,
            ns3_tool,
            constructor_bin,
            topology=args.topology,
            scale_name=scale_name,
            scale=scale,
            routing=routing,
            repeat=repeat,
            threads=threads,
            config_path=config_path,
            traffic_pattern=args.traffic_pattern,
            data_size=data_size,
            degree=args.degree,
            allreduce_group_size=args.allreduce_group_size,
            allreduce_placement=args.allreduce_placement,
            allreduce_step_gap=args.allreduce_step_gap,
            profile=args.profile,
            log_dir=log_dir,
        )
        rows.append(row)
        if row.get("rc") == "0":
            completed.add(current_key)
        write_rows(runs_path, rows)

    if not pending:
        print("[RESUME] no pending cases; all requested cases are already complete")
    write_rows(runs_path, rows)
    write_summary(stats_path, rows)
    print(f"stats={stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
