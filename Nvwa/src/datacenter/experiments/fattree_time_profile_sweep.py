#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproducible FatTree initialization time profiling sweep for constructor --timeProfile=true.

Outputs one self-contained run directory with:
  - manifest.json
  - configs/*.json
  - logs/*.log
  - summary, time-profile, and time-breakdown CSVs

Run from the repository root, for example:
  python3 src/datacenter/experiments/fattree_time_profile_sweep.py \
    --skip-build \
    --routings RuleBased,NodeBfs \
    --k-values 4,6,8,10,12,14,16 \
    --repeats 1
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
from typing import Any, Dict, Iterable, List, Tuple


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
GENERATOR_DIR = ROOT / "src/datacenter/examples/inputs"
if str(GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATOR_DIR))

from topology_generator import TopologyGenerator  # noqa: E402


RE_INIT_TIME = re.compile(r"\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_EXEC_TIME = re.compile(r"\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_BFS_TIME = re.compile(r"\bBFS\s+routing\s+time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_ROUTING = re.compile(r"\bRouting\s+algorithm:\s*(\S+)\b", re.I)
RE_HOST_NUMBER = re.compile(r"\bHost\s+number:\s*([0-9]+)\b", re.I)
RE_INIT_TIME_PROFILE_SUMMARY = re.compile(r"Initialization time profile summary:\s*(.*)$", re.I)
RE_INIT_TIME_PROFILE = re.compile(r"Initialization time profile:\s*stage=([^\s]+)\s*(.*)$", re.I)
RE_TRAFFIC = re.compile(r"Traffic generated:\s*(.*)$", re.I)
RE_KV = re.compile(r"\b([A-Za-z_]+)=([^\s]+)\b")


@dataclass(frozen=True)
class FatTreeSize:
    k: int

    @property
    def tag(self) -> str:
        return f"k{self.k}"

    @property
    def theoretical_hosts(self) -> int:
        return self.k ** 3 // 4


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_k_values(text: str) -> List[FatTreeSize]:
    sizes: List[FatTreeSize] = []
    for raw in text.split(","):
        part = raw.strip()
        if not part:
            continue
        k = int(part)
        if k <= 0 or k % 2 != 0:
            raise SystemExit(f"Bad FatTree k '{part}': k must be a positive even integer")
        sizes.append(FatTreeSize(k=k))
    if not sizes:
        raise SystemExit("No FatTree k values parsed")
    return sizes


def parse_csv_list(text: str) -> List[str]:
    values = [x.strip() for x in text.split(",") if x.strip()]
    if not values:
        raise SystemExit("Empty comma-separated list")
    return values


def parse_kv(text: str) -> Dict[str, str]:
    return {key: value.rstrip(",") for key, value in RE_KV.findall(text)}


def pick_ns3_tool(root: Path) -> Path:
    for name in ("ns3", "ns", "waf"):
        candidate = root / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit("Cannot find executable ./ns3, ./ns, or ./waf in repository root")


def run_logged(cmd: List[str], cwd: Path, log_path: Path) -> Tuple[int, float, str]:
    ensure_dir(log_path.parent)
    start = time.time()
    chunks: List[str] = []
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
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            chunks.append(line)
        rc = proc.wait()
        wall_s = time.time() - start
        log.write(f"\n[rc={rc} wall_s={wall_s:.6f}]\n")
    return rc, wall_s, "".join(chunks)


def configure_and_build(ns3_tool: Path, build_profile: str) -> None:
    build_log = ROOT / "results" / f"build-fattree-time-profile-{timestamp()}.log"
    if ns3_tool.name in ("ns3", "ns"):
        cfg_cmd = [
            str(ns3_tool),
            "configure",
            f"--build-profile={build_profile}",
            "--enable-examples",
        ]
        rc, _, _ = run_logged(cfg_cmd, ROOT, build_log)
        if rc != 0:
            raise SystemExit(f"configure failed, see {build_log}")
        rc, _, _ = run_logged([str(ns3_tool), "build", "constructor"], ROOT, build_log)
        if rc != 0:
            raise SystemExit(f"build failed, see {build_log}")
    else:
        cfg_cmd = [str(ns3_tool), "configure", f"--build-profile={build_profile}", "--enable-examples"]
        rc, _, _ = run_logged(cfg_cmd, ROOT, build_log)
        if rc != 0:
            raise SystemExit(f"waf configure failed, see {build_log}")
        rc, _, _ = run_logged([str(ns3_tool), "build"], ROOT, build_log)
        if rc != 0:
            raise SystemExit(f"waf build failed, see {build_log}")


def fattree_config(size: FatTreeSize, bandwidth: str, delay: str) -> Dict[str, Any]:
    return TopologyGenerator().generate(
        "fattree",
        k=size.k,
        bandwidth=bandwidth,
        delay=delay,
        routing="RuleBased",
    )


def write_configs(sizes: Iterable[FatTreeSize], config_dir: Path, bandwidth: str, delay: str) -> Dict[str, Path]:
    ensure_dir(config_dir)
    paths: Dict[str, Path] = {}
    for size in sizes:
        path = config_dir / f"fattree_{size.tag}_{bandwidth}_{delay}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fattree_config(size, bandwidth, delay), f, indent=2)
            f.write("\n")
        paths[size.tag] = path
    return paths


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


def parse_output(output: str, wall_s: float) -> Dict[str, Any]:
    agg: Dict[str, Any] = {"wall_s": wall_s}
    time_rows: List[Dict[str, Any]] = []
    traffic: Dict[str, str] = {}

    for line in output.splitlines():
        if match := RE_ROUTING.search(line):
            agg["routing"] = match.group(1)
        if match := RE_INIT_TIME.search(line):
            agg["init_s"] = match.group(1)
        if match := RE_EXEC_TIME.search(line):
            agg["exec_s"] = match.group(1)
        if match := RE_BFS_TIME.search(line):
            agg["bfs_routing_s"] = match.group(1)
        if match := RE_HOST_NUMBER.search(line):
            agg["host_num"] = int(match.group(1))
        if match := RE_INIT_TIME_PROFILE_SUMMARY.search(line):
            agg["_time_profile_summary"] = parse_kv(match.group(1))
        if match := RE_INIT_TIME_PROFILE.search(line):
            row = parse_kv(match.group(2))
            row["stage"] = match.group(1)
            time_rows.append(row)
        if match := RE_TRAFFIC.search(line):
            traffic = parse_kv(match.group(1))

    agg["_time_profile"] = time_rows
    agg["_traffic"] = traffic
    return agg


def find_time_row(agg: Dict[str, Any], stage: str) -> Dict[str, Any]:
    for row in agg.get("_time_profile", []):
        if isinstance(row, dict) and row.get("stage") == stage:
            return row
    return {}


def float_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def str_float(value: float) -> str:
    return f"{value:.6f}"


def pct(part: float, total: float) -> str:
    return f"{(100.0 * part / total if total else 0.0):.2f}"


def write_manifest(path: Path, args: argparse.Namespace, ns3_tool: Path, sizes: List[FatTreeSize]) -> None:
    manifest = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(ROOT),
        "git_sha": git_sha(ROOT),
        "git_dirty": git_dirty(ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "ns3_tool": str(ns3_tool),
        "argv": sys.argv,
        "topology": "fattree",
        "k_values": [size.k for size in sizes],
        "sizes": [
            {
                "k": size.k,
                "theoretical_hosts": size.theoretical_hosts,
            }
            for size in sizes
        ],
        "routings": parse_csv_list(args.routings),
        "repeats": args.repeats,
        "data_size": args.data_size,
        "data_rate": args.data_rate,
        "degree": args.degree,
        "packet_size": args.packet_size,
        "traffic_pattern": args.traffic_pattern,
        "traffic_replay_mode": args.traffic_replay_mode,
        "bandwidth": args.bandwidth,
        "delay": args.delay,
        "init_only": not args.run_simulation,
        "memory_profile": args.memory_profile,
        "build_profile": args.build_profile,
        "skip_build": args.skip_build,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def ns3_run_command(ns3_tool: Path,
                    config_path: Path,
                    routing: str,
                    data_size: int,
                    data_rate: str,
                    degree: int,
                    packet_size: int,
                    traffic_pattern: str,
                    traffic_replay_mode: str,
                    init_only: bool,
                    memory_profile: bool) -> List[str]:
    program = [
        "constructor",
        f"--config={config_path}",
        f"--routing={routing}",
        f"--dataSize={data_size}",
        f"--dataRate={data_rate}",
        f"--degree={degree}",
        f"--packetSize={packet_size}",
        f"--trafficPattern={traffic_pattern}",
        f"--trafficReplayMode={traffic_replay_mode}",
        "--timeProfile=true",
        f"--initOnly={'true' if init_only else 'false'}",
        f"--memory={'true' if memory_profile else 'false'}",
    ]
    return [str(ns3_tool), "run", " ".join(program), "--no-build"]


SUMMARY_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "rc",
    "init_s",
    "init_profile_total_s",
    "init_profile_accounted_s",
    "init_profile_other_s",
    "wall_s",
    "exec_s",
    "bfs_routing_s",
    "hosts",
    "theoretical_hosts",
    "generated_pattern",
    "generated_flows",
    "logical_steps",
    "chunk_bytes",
    "aggregated_bytes",
    "topology_build_s",
    "routing_computation_s",
    "topology_plus_routing_other_s",
    "topology_build_pct",
    "routing_computation_pct",
    "topology_plus_routing_other_pct",
    "config_json_s",
    "routing_helper_setup_s",
    "template_build_s",
    "address_registration_s",
    "traffic_generation_s",
    "application_setup_s",
    "residual_other_s",
    "config",
    "log",
    "cmd",
]


TIME_PROFILE_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "stage",
    "category",
    "duration_s",
    "share_pct",
    "accounted",
    "detail",
    "total_s",
    "accounted_s",
    "other_s",
    "samples",
]


TIME_BREAKDOWN_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "init_total_s",
    "topology_build_s",
    "routing_computation_s",
    "other_s",
    "topology_pct",
    "routing_pct",
    "other_pct",
    "config_json_s",
    "template_build_s",
    "address_registration_s",
    "traffic_generation_s",
    "application_setup_s",
    "residual_other_s",
    "log",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible FatTree initialization time profiling sweeps.")
    parser.add_argument(
        "--k-values",
        default="4,8,12,16",
        help="Comma list of even FatTree k values.",
    )
    parser.add_argument("--routings", default="RuleBased,NodeBfs", help="Comma list, e.g. NodeBfs,RuleBased,Global.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--data-size", type=int, default=1048576)
    parser.add_argument("--data-rate", default="100Gbps")
    parser.add_argument("--degree", type=int, default=4)
    parser.add_argument("--packet-size", type=int, default=1000)
    parser.add_argument("--traffic-pattern", default="allreduce", choices=["allreduce", "alltoall", "flows"])
    parser.add_argument("--traffic-replay-mode", default="batch", choices=["batch", "onoff"])
    parser.add_argument("--bandwidth", default="100Gbps")
    parser.add_argument("--delay", default="1us")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--summary-name", default="experiment_3_summary.csv")
    parser.add_argument("--time-profile-name", default="experiment_3_time_profile.csv")
    parser.add_argument("--time-breakdown-name", default="experiment_3_time_breakdown.csv")
    parser.add_argument("--run-simulation", action="store_true", help="Run Simulator::Run after initialization.")
    parser.add_argument("--memory-profile", action="store_true", help="Also enable constructor --memory=true.")
    parser.add_argument("--build-profile", default="optimized", choices=["debug", "default", "release", "optimized", "minsizerel"])
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")

    sizes = parse_k_values(args.k_values)
    routings = parse_csv_list(args.routings)
    ns3_tool = pick_ns3_tool(ROOT)

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "results" / f"fattree-time-profile-{timestamp()}"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    config_dir = out_dir / "configs"
    log_dir = out_dir / "logs"
    ensure_dir(out_dir)
    ensure_dir(log_dir)

    if not args.skip_build:
        configure_and_build(ns3_tool, args.build_profile)

    config_paths = write_configs(sizes, config_dir, args.bandwidth, args.delay)
    write_manifest(out_dir / "manifest.json", args, ns3_tool, sizes)

    summary_path = out_dir / args.summary_name
    time_profile_path = out_dir / args.time_profile_name
    time_breakdown_path = out_dir / args.time_breakdown_name

    with open(summary_path, "w", newline="", encoding="utf-8") as summary_file, \
         open(time_profile_path, "w", newline="", encoding="utf-8") as time_file, \
         open(time_breakdown_path, "w", newline="", encoding="utf-8") as breakdown_file:
        summary_writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_FIELDS)
        time_writer = csv.DictWriter(time_file, fieldnames=TIME_PROFILE_FIELDS)
        breakdown_writer = csv.DictWriter(breakdown_file, fieldnames=TIME_BREAKDOWN_FIELDS)
        summary_writer.writeheader()
        time_writer.writeheader()
        breakdown_writer.writeheader()

        total_cases = len(sizes) * len(routings) * args.repeats
        done = 0
        for size in sizes:
            config_path = config_paths[size.tag]
            for routing in routings:
                for repeat in range(1, args.repeats + 1):
                    done += 1
                    case_id = f"fattree_{size.tag}_{routing}_r{repeat}"
                    log_path = log_dir / f"{case_id}.log"
                    cmd = ns3_run_command(
                        ns3_tool,
                        config_path,
                        routing,
                        args.data_size,
                        args.data_rate,
                        args.degree,
                        args.packet_size,
                        args.traffic_pattern,
                        args.traffic_replay_mode,
                        not args.run_simulation,
                        args.memory_profile,
                    )
                    print(f"[{done}/{total_cases}] {case_id}")
                    rc, wall_s, output = run_logged(cmd, ROOT, log_path)
                    agg = parse_output(output, wall_s)

                    summary = agg.get("_time_profile_summary", {})
                    if not isinstance(summary, dict):
                        summary = {}
                    traffic = agg.get("_traffic", {})
                    if not isinstance(traffic, dict):
                        traffic = {}

                    total_s = float_value(summary.get("total_s"))
                    topology_s = float_value(find_time_row(agg, "topology_build").get("duration_s"))
                    routing_s = float_value(find_time_row(agg, "routing_computation").get("duration_s"))
                    top_route_other_s = max(0.0, total_s - topology_s - routing_s)

                    summary_writer.writerow({
                        "case_id": case_id,
                        "repeat": repeat,
                        "routing": agg.get("routing", routing),
                        "k": size.k,
                        "rc": rc,
                        "init_s": agg.get("init_s", ""),
                        "init_profile_total_s": summary.get("total_s", ""),
                        "init_profile_accounted_s": summary.get("accounted_s", ""),
                        "init_profile_other_s": summary.get("other_s", ""),
                        "wall_s": agg.get("wall_s", wall_s),
                        "exec_s": agg.get("exec_s", ""),
                        "bfs_routing_s": agg.get("bfs_routing_s", ""),
                        "hosts": agg.get("host_num", ""),
                        "theoretical_hosts": size.theoretical_hosts,
                        "generated_pattern": traffic.get("pattern", ""),
                        "generated_flows": traffic.get("flows", ""),
                        "logical_steps": traffic.get("logical_steps", ""),
                        "chunk_bytes": traffic.get("chunk_bytes", ""),
                        "aggregated_bytes": traffic.get("aggregated_bytes", ""),
                        "topology_build_s": str_float(topology_s),
                        "routing_computation_s": str_float(routing_s),
                        "topology_plus_routing_other_s": str_float(top_route_other_s),
                        "topology_build_pct": pct(topology_s, total_s),
                        "routing_computation_pct": pct(routing_s, total_s),
                        "topology_plus_routing_other_pct": pct(top_route_other_s, total_s),
                        "config_json_s": find_time_row(agg, "config_json").get("duration_s", ""),
                        "routing_helper_setup_s": find_time_row(agg, "routing_helper_setup").get("duration_s", ""),
                        "template_build_s": find_time_row(agg, "template_build").get("duration_s", ""),
                        "address_registration_s": find_time_row(agg, "address_registration").get("duration_s", ""),
                        "traffic_generation_s": find_time_row(agg, "traffic_generation").get("duration_s", ""),
                        "application_setup_s": find_time_row(agg, "application_setup").get("duration_s", ""),
                        "residual_other_s": find_time_row(agg, "other").get("duration_s", ""),
                        "config": str(config_path),
                        "log": str(log_path),
                        "cmd": shlex.join(cmd),
                    })

                    for row in agg.get("_time_profile", []):
                        if not isinstance(row, dict):
                            continue
                        time_writer.writerow({
                            "case_id": case_id,
                            "repeat": repeat,
                            "routing": agg.get("routing", routing),
                            "k": size.k,
                            "stage": row.get("stage", ""),
                            "category": row.get("category", ""),
                            "duration_s": row.get("duration_s", ""),
                            "share_pct": row.get("share_pct", ""),
                            "accounted": row.get("accounted", ""),
                            "detail": row.get("detail", ""),
                            "total_s": summary.get("total_s", ""),
                            "accounted_s": summary.get("accounted_s", ""),
                            "other_s": summary.get("other_s", ""),
                            "samples": summary.get("samples", ""),
                        })

                    breakdown_row = {
                        "case_id": case_id,
                        "repeat": repeat,
                        "routing": agg.get("routing", routing),
                        "k": size.k,
                        "init_total_s": str_float(total_s),
                        "topology_build_s": str_float(topology_s),
                        "routing_computation_s": str_float(routing_s),
                        "other_s": str_float(top_route_other_s),
                        "topology_pct": pct(topology_s, total_s),
                        "routing_pct": pct(routing_s, total_s),
                        "other_pct": pct(top_route_other_s, total_s),
                        "config_json_s": find_time_row(agg, "config_json").get("duration_s", ""),
                        "template_build_s": find_time_row(agg, "template_build").get("duration_s", ""),
                        "address_registration_s": find_time_row(agg, "address_registration").get("duration_s", ""),
                        "traffic_generation_s": find_time_row(agg, "traffic_generation").get("duration_s", ""),
                        "application_setup_s": find_time_row(agg, "application_setup").get("duration_s", ""),
                        "residual_other_s": find_time_row(agg, "other").get("duration_s", ""),
                        "log": str(log_path),
                    }
                    breakdown_writer.writerow(breakdown_row)

                    summary_file.flush()
                    time_file.flush()
                    breakdown_file.flush()

                    if rc != 0:
                        print(f"[WARN] {case_id} failed with rc={rc}; see {log_path}")

    print(f"[DONE] {out_dir}")
    print(f"  summary   : {summary_path}")
    print(f"  time      : {time_profile_path}")
    print(f"  breakdown : {time_breakdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
