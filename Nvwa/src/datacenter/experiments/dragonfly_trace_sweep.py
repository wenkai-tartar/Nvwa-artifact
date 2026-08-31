#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run real trace replay on generated Dragonfly topologies.

Example:
  python3 src/datacenter/experiments/dragonfly_trace_sweep.py \
    --skip-build \
    --h-values 4 \
    --routings RuleBased,NodeBfs \
    --traffic-trace /data/wkli/nvwa-atlahs/grok314b_n256/grok_n256.200perrank.nvwa.csv \
    --traffic-trace-max-flows 1000 \
    --packet-size 64000
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


ROOT = repo_root()
GENERATOR_DIR = ROOT / "src/datacenter/examples/inputs"
if str(GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATOR_DIR))

from topology_generator import TopologyGenerator  # noqa: E402


RE_INIT_TIME = re.compile(r"\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_EXEC_TIME = re.compile(r"\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_INIT_MEM = re.compile(r"\bInitialization\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_EXEC_MEM = re.compile(r"\bExecution\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_ROUTING = re.compile(r"\bRouting algorithm\s*:\s*([^\s]+)\b", re.I)
RE_HOST_NUMBER = re.compile(r"\bHost\s+number:\s*([0-9]+)\b", re.I)
RE_TRACE_FLOWS = re.compile(r"\bTraffic\s*trace\s*flows\s*:\s*([0-9]+)\b", re.I)
RE_OBJECT_PROFILE = re.compile(r"Initialization object profile:\s*stage=([^\s]+)\s*(.*)$", re.I)
RE_FORWARD = re.compile(r"\bFORWARD_STATS\b(.*)$", re.I)
RE_KV_INT = re.compile(r"\b([A-Za-z_]+)=([0-9]+)\b")
RE_KV = re.compile(r"\b([A-Za-z_]+)=([^\s]+)\b")


@dataclass(frozen=True)
class DragonflySize:
    h: int

    @property
    def a(self) -> int:
        return 2 * self.h

    @property
    def p(self) -> int:
        return self.h

    @property
    def g(self) -> int:
        return self.a * self.h + 1

    @property
    def hosts(self) -> int:
        return self.g * self.a * self.p

    @property
    def tag(self) -> str:
        return f"h{self.h}_g{self.g}_a{self.a}_p{self.p}"


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_csv_list(text: str) -> List[str]:
    values = [item.strip() for item in text.split(",") if item.strip()]
    if not values:
        raise SystemExit("Empty comma-separated list")
    return values


def minimum_size_for_hosts(required_hosts: int) -> DragonflySize:
    h = 2
    while True:
        size = DragonflySize(h=h)
        if size.hosts >= required_hosts:
            return size
        h += 1


def parse_h_values(text: str, required_hosts: int) -> List[DragonflySize]:
    sizes: List[DragonflySize] = []
    for raw in text.split(","):
        part = raw.strip()
        if not part:
            continue
        if part.lower() == "auto":
            sizes.append(minimum_size_for_hosts(required_hosts))
            continue
        h = int(part)
        if h <= 0:
            raise SystemExit(f"Bad Dragonfly h '{part}': h must be positive")
        sizes.append(DragonflySize(h=h))
    if not sizes:
        raise SystemExit("No Dragonfly h values parsed")
    unique_sizes: Dict[int, DragonflySize] = {}
    for size in sizes:
        unique_sizes[size.h] = size
    return [unique_sizes[h] for h in sorted(unique_sizes)]


def parse_kv(text: str) -> Dict[str, str]:
    return {key: value.rstrip(",") for key, value in RE_KV.findall(text)}


def pick_constructor_binary(root: Path, build_profile: str) -> Optional[Path]:
    ex_dir = root / "build/src/datacenter/examples"
    candidates = [
        ex_dir / f"ns3-dev-constructor-{build_profile}",
        ex_dir / f"ns3.42-constructor-{build_profile}",
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    if ex_dir.exists():
        for candidate in sorted(ex_dir.glob(f"*constructor*{build_profile}*")):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def build_constructor(root: Path) -> None:
    cmd = ["./ns3", "build", "constructor"]
    proc = subprocess.run(cmd, cwd=root, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"constructor build failed with rc={proc.returncode}")


def dragonfly_config(size: DragonflySize, bandwidth: str, delay: str) -> Dict[str, Any]:
    return TopologyGenerator().generate(
        "dragonfly",
        groups=size.g,
        routers_per_group=size.a,
        hosts_per_router=size.p,
        global_links_per_router=size.h,
        global_link_arrangement="Absolute",
        bandwidth=bandwidth,
        delay=delay,
        routing="RuleBased",
    )


def write_configs(sizes: Iterable[DragonflySize], out_dir: Path, bandwidth: str, delay: str) -> Dict[int, Path]:
    ensure_dir(out_dir)
    paths: Dict[int, Path] = {}
    for size in sizes:
        path = out_dir / f"dragonfly_{size.tag}_{bandwidth}_{delay}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(dragonfly_config(size, bandwidth, delay), f, indent=2)
            f.write("\n")
        paths[size.h] = path
    return paths


def scan_trace(path: Path, max_flows: int) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"traffic trace does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"traffic trace is not a file: {path}")

    flows = 0
    min_rank = 2**63 - 1
    max_rank = -1
    total_bytes = 0
    min_start_s: Optional[float] = None
    max_start_s: Optional[float] = None
    ranks = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"src", "dst", "bytes"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise SystemExit(f"trace must have columns including {sorted(required)}: {path}")
        for row in reader:
            if max_flows > 0 and flows >= max_flows:
                break
            try:
                src = int(row["src"])
                dst = int(row["dst"])
                size = int(float(row["bytes"]))
                start_s = float(row.get("start_s", 0.0) or 0.0)
            except Exception as exc:
                raise SystemExit(f"failed to parse trace row {flows + 2}: {exc}") from exc
            min_rank = min(min_rank, src, dst)
            max_rank = max(max_rank, src, dst)
            ranks.add(src)
            ranks.add(dst)
            total_bytes += max(0, size)
            min_start_s = start_s if min_start_s is None else min(min_start_s, start_s)
            max_start_s = start_s if max_start_s is None else max(max_start_s, start_s)
            flows += 1
    if flows == 0:
        raise SystemExit(f"trace produced no flows: {path}")
    missing_rank_count = 0
    if min_rank == 0:
        missing_rank_count = sum(1 for rank in range(max_rank + 1) if rank not in ranks)
    return {
        "flows_scanned": flows,
        "min_rank": min_rank,
        "max_rank": max_rank,
        "unique_ranks": len(ranks),
        "missing_rank_count_in_0_to_max": missing_rank_count,
        "required_hosts": max_rank + 1,
        "total_bytes_scanned": total_bytes,
        "min_start_s": min_start_s or 0.0,
        "max_start_s": max_start_s or 0.0,
    }


def git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True).strip()
    except Exception:
        return "unknown"


def git_dirty(root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "status", "--short"], cwd=str(root), text=True)
        return "yes" if out.strip() else "no"
    except Exception:
        return "unknown"


def write_manifest(path: Path,
                   args: argparse.Namespace,
                   sizes: List[DragonflySize],
                   trace_stats: Dict[str, int]) -> None:
    manifest = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(ROOT),
        "git_sha": git_sha(ROOT),
        "git_dirty": git_dirty(ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "argv": sys.argv,
        "topology": "dragonfly",
        "dragonfly_sizes": [
            {"h": size.h, "g": size.g, "a": size.a, "p": size.p, "hosts": size.hosts}
            for size in sizes
        ],
        "routings": parse_csv_list(args.routings),
        "traffic_trace": str(Path(args.traffic_trace).resolve()),
        "trace_stats": trace_stats,
        "traffic_trace_max_flows": args.traffic_trace_max_flows,
        "packet_size": args.packet_size,
        "rank_to_host_mapping": "rank i maps to Dragonfly host index i",
        "bandwidth": args.bandwidth,
        "delay": args.delay,
        "memory": not args.no_memory,
        "build_profile": args.build_profile,
        "skip_build": args.skip_build,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def parse_metrics(stdout: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    result["init_s"] = RE_INIT_TIME.search(stdout).group(1) if RE_INIT_TIME.search(stdout) else ""
    result["exec_s"] = RE_EXEC_TIME.search(stdout).group(1) if RE_EXEC_TIME.search(stdout) else ""
    result["routing"] = RE_ROUTING.search(stdout).group(1) if RE_ROUTING.search(stdout) else ""
    result["init_peak_mem_kb"] = RE_INIT_MEM.search(stdout).group(1) if RE_INIT_MEM.search(stdout) else ""
    result["exec_peak_mem_kb"] = RE_EXEC_MEM.search(stdout).group(1) if RE_EXEC_MEM.search(stdout) else ""
    result["traffic_trace_flows"] = RE_TRACE_FLOWS.search(stdout).group(1) if RE_TRACE_FLOWS.search(stdout) else ""
    result["host_num"] = RE_HOST_NUMBER.search(stdout).group(1) if RE_HOST_NUMBER.search(stdout) else ""

    object_profiles: Dict[str, Dict[str, int]] = {}
    forward: Dict[str, str] = {}
    for line in stdout.splitlines():
        if match := RE_OBJECT_PROFILE.search(line):
            object_profiles[match.group(1)] = {key: int(value) for key, value in RE_KV_INT.findall(match.group(2))}
        if match := RE_FORWARD.search(line):
            forward = parse_kv(match.group(1))

    object_profile = object_profiles.get("post_applications") or object_profiles.get("post_routing") or {}
    for key in ["nodes", "rule_based_rules", "routing_entries", "applications"]:
        result[key] = str(object_profile.get(key, ""))
    result["forward_count"] = forward.get("count", "")
    return result


def run_case(root: Path,
             constructor_bin: Optional[Path],
             config_path: Path,
             size: DragonflySize,
             routing: str,
             args: argparse.Namespace,
             log_dir: Path) -> Dict[str, str]:
    ensure_dir(log_dir)
    trace_path = Path(args.traffic_trace).resolve()
    case_id = f"dragonfly_{size.tag}_{routing}"
    log_path = log_dir / f"{case_id}.log"
    cmd_args = [
        f"--config={config_path}",
        f"--routing={routing}",
        "--trafficPattern=trace",
        f"--trafficReplayMode={args.traffic_replay_mode}",
        f"--trafficTrace={trace_path}",
        f"--trafficTraceMaxFlows={args.traffic_trace_max_flows}",
        f"--trafficTraceTimeScale={args.traffic_trace_time_scale}",
        f"--trafficStartOffset={args.traffic_start_offset}",
        f"--trafficTraceStopPadding={args.traffic_trace_stop_padding}",
        f"--packetSize={args.packet_size}",
        f"--dataRate={args.data_rate}",
        f"--memory={'false' if args.no_memory else 'true'}",
    ]
    if constructor_bin:
        cmd = [str(constructor_bin), *cmd_args]
    else:
        cmd = ["./ns3", "run", "constructor " + " ".join(cmd_args), "--no-build"]

    start = time.time()
    proc = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wall_s = time.time() - start
    log_path.write_text("$ " + shlex.join(cmd) + "\n\n" + proc.stdout, encoding="utf-8")
    metrics = parse_metrics(proc.stdout)
    exec_peak_kb = metrics.get("exec_peak_mem_kb", "")
    exec_peak_gb = ""
    if exec_peak_kb:
        exec_peak_gb = f"{int(exec_peak_kb) / (1024.0 * 1024.0):.6f}"

    row = {
        "case_id": case_id,
        "h": str(size.h),
        "g": str(size.g),
        "a": str(size.a),
        "p": str(size.p),
        "dragonfly_hosts": str(size.hosts),
        "routing": metrics.get("routing") or routing,
        "rc": str(proc.returncode),
        "traffic_trace": str(trace_path),
        "traffic_trace_max_flows": str(args.traffic_trace_max_flows),
        "traffic_trace_flows": metrics.get("traffic_trace_flows", ""),
        "trace_required_hosts": str(args.trace_stats["required_hosts"]),
        "trace_unique_ranks": str(args.trace_stats["unique_ranks"]),
        "trace_max_rank": str(args.trace_stats["max_rank"]),
        "packet_size": str(args.packet_size),
        "host_num": metrics.get("host_num", ""),
        "nodes": metrics.get("nodes", ""),
        "rule_based_rules": metrics.get("rule_based_rules", ""),
        "routing_entries": metrics.get("routing_entries", ""),
        "applications": metrics.get("applications", ""),
        "init_s": metrics.get("init_s", ""),
        "exec_s": metrics.get("exec_s", ""),
        "wall_s": f"{wall_s:.6f}",
        "init_peak_mem_kb": metrics.get("init_peak_mem_kb", ""),
        "exec_peak_mem_kb": exec_peak_kb,
        "exec_peak_mem_gb": exec_peak_gb,
        "forward_count": metrics.get("forward_count", ""),
        "config": str(config_path),
        "log": str(log_path),
        "cmd": shlex.join(cmd),
    }
    return row


CSV_FIELDS = [
    "case_id",
    "h",
    "g",
    "a",
    "p",
    "dragonfly_hosts",
    "routing",
    "rc",
    "traffic_trace",
    "traffic_trace_max_flows",
    "traffic_trace_flows",
    "trace_required_hosts",
    "trace_unique_ranks",
    "trace_max_rank",
    "packet_size",
    "host_num",
    "nodes",
    "rule_based_rules",
    "routing_entries",
    "applications",
    "init_s",
    "exec_s",
    "wall_s",
    "init_peak_mem_kb",
    "exec_peak_mem_kb",
    "exec_peak_mem_gb",
    "forward_count",
    "config",
    "log",
    "cmd",
]


def write_summary(path: Path, rows: List[Dict[str, str]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--h-values",
        default="auto",
        help="Comma list of Dragonfly h values, or auto for the minimum h>=2 that covers the trace ranks.",
    )
    parser.add_argument("--routings", default="RuleBased,NodeBfs")
    parser.add_argument("--traffic-trace", required=True)
    parser.add_argument("--traffic-trace-max-flows", type=int, default=0, help="0 means all flows.")
    parser.add_argument("--traffic-replay-mode", default="batch", choices=["batch", "onoff"])
    parser.add_argument("--traffic-trace-time-scale", type=float, default=1.0)
    parser.add_argument("--traffic-start-offset", type=float, default=1.0)
    parser.add_argument("--traffic-trace-stop-padding", type=float, default=1.0)
    parser.add_argument("--packet-size", type=int, default=64000)
    parser.add_argument("--data-rate", default="100Gbps")
    parser.add_argument("--bandwidth", default="100Gbps")
    parser.add_argument("--delay", default="1us")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--summary-name", default="experiment_6.csv")
    parser.add_argument("--build-profile", default="optimized")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    args = parser.parse_args()

    if args.packet_size <= 0:
        raise SystemExit("--packet-size must be positive")
    if args.traffic_trace_max_flows < 0:
        raise SystemExit("--traffic-trace-max-flows must be non-negative")

    routings = parse_csv_list(args.routings)
    trace_stats = scan_trace(Path(args.traffic_trace), args.traffic_trace_max_flows)
    sizes = parse_h_values(args.h_values, trace_stats["required_hosts"])
    for size in sizes:
        if size.hosts < trace_stats["required_hosts"]:
            raise SystemExit(
                f"Dragonfly h={size.h} has {size.hosts} hosts, but trace requires "
                f"{trace_stats['required_hosts']} hosts from max rank {trace_stats['max_rank']}"
            )

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "results" / f"dragonfly-trace-{timestamp()}"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    config_dir = out_dir / "configs"
    log_dir = out_dir / "logs"
    ensure_dir(out_dir)
    ensure_dir(log_dir)

    if not args.skip_build:
        build_constructor(ROOT)
    constructor_bin = pick_constructor_binary(ROOT, args.build_profile)
    args.trace_stats = trace_stats
    configs = write_configs(sizes, config_dir, args.bandwidth, args.delay)
    write_manifest(out_dir / "manifest.json", args, sizes, trace_stats)

    rows: List[Dict[str, str]] = []
    summary_path = out_dir / args.summary_name
    total = len(sizes) * len(routings)
    done = 0
    for size in sizes:
        for routing in routings:
            done += 1
            print(f"[{done}/{total}] dragonfly {size.tag} {routing}")
            row = run_case(ROOT, constructor_bin, configs[size.h], size, routing, args, log_dir)
            rows.append(row)
            write_summary(summary_path, rows)
            print(
                f"  rc={row['rc']} init={row['init_s']}s exec={row['exec_s']}s "
                f"exec_peak={row['exec_peak_mem_kb']}KB flows={row['traffic_trace_flows']}"
            )
            if row["rc"] != "0":
                print(f"[WARN] failed case; see {row['log']}")

    print(f"[DONE] {out_dir}")
    print(f"  summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
