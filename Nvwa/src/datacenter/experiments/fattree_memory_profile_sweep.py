#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproducible FatTree memory profiling sweep for constructor --memory=true.

Outputs one self-contained run directory with:
  - manifest.json
  - configs/*.json
  - logs/*.log
  - summary, memory-profile, and object-profile CSVs

Run from the repository root, for example:
  python3 src/datacenter/experiments/fattree_memory_profile_sweep.py \
    --skip-build \
    --routings NodeBfs \
    --k-values 4,8,12,16 \
    --repeats 3
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

from exp import parse_stdout_line  # noqa: E402
from topology_generator import TopologyGenerator  # noqa: E402


RE_HOST_NUMBER = re.compile(r"\bHost\s+number:\s*([0-9]+)\b", re.I)


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
    build_log = ROOT / "results" / f"build-fattree-memory-profile-{timestamp()}.log"
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
    agg: Dict[str, Any] = {}
    for line in output.splitlines():
        parse_stdout_line(line, agg)
        if (match := RE_HOST_NUMBER.search(line)):
            agg["host_num"] = int(match.group(1))
    agg.setdefault("wall_s", wall_s)
    return agg


def find_profile_row(agg: Dict[str, Any], *, stage: str) -> Dict[str, Any]:
    for row in agg.get("_memory_profile", []):
        if isinstance(row, dict) and row.get("stage") == stage:
            return row
    return {}


def find_object_row(agg: Dict[str, Any], preferred_stages: Iterable[str]) -> Dict[str, Any]:
    rows = [row for row in agg.get("_object_profile", []) if isinstance(row, dict)]
    for stage in preferred_stages:
        for row in rows:
            if row.get("stage") == stage:
                return row
    return rows[-1] if rows else {}


def kb_value(value: Any) -> Any:
    if value in (None, ""):
        return ""
    return int(float(value))


def gb_from_kb(value: Any) -> Any:
    if value in (None, ""):
        return ""
    return float(value) / (1024.0 * 1024.0)


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
        "degree": args.degree,
        "traffic_pattern": args.traffic_pattern,
        "bandwidth": args.bandwidth,
        "delay": args.delay,
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
                    degree: int,
                    traffic_pattern: str) -> List[str]:
    program = [
        "constructor",
        f"--config={config_path}",
        f"--routing={routing}",
        f"--dataSize={data_size}",
        f"--degree={degree}",
        f"--trafficPattern={traffic_pattern}",
        "--memory=true",
    ]
    return [str(ns3_tool), "run", " ".join(program), "--no-build"]


SUMMARY_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "rc",
    "init_s",
    "exec_s",
    "wall_s",
    "init_peak_mem_kb",
    "init_peak_mem_gb",
    "exec_peak_mem_kb",
    "exec_peak_mem_gb",
    "routing_state_delta_kb",
    "routing_state_share_pct",
    "topology_build_delta_kb",
    "topology_build_share_pct",
    "applications_delta_kb",
    "applications_share_pct",
    "nodes",
    "hosts",
    "netdevices",
    "channels",
    "ipv4_interfaces",
    "routing_entries",
    "applications",
    "config",
    "log",
    "cmd",
]


MEMORY_PROFILE_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "stage",
    "category",
    "rss_kb",
    "delta_kb",
    "share_pct",
    "detail",
    "pid",
    "start_rss_kb",
    "final_rss_kb",
    "total_delta_kb",
    "positive_delta_kb",
    "samples",
]


OBJECT_PROFILE_FIELDS = [
    "case_id",
    "repeat",
    "routing",
    "k",
    "stage",
    "levels",
    "nodes",
    "netdevices",
    "p2p_netdevices",
    "channels",
    "ipv4",
    "ipv4_interfaces",
    "routing_protocols",
    "rule_based_protocols",
    "node_bfs_protocols",
    "rule_based_rules",
    "routing_entries",
    "applications",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible FatTree memory profiling sweeps.")
    parser.add_argument(
        "--k-values",
        default="4,8,12,16",
        help="Comma list of even FatTree k values.",
    )
    parser.add_argument("--routings", default="NodeBfs", help="Comma list, e.g. NodeBfs,RuleBased,Global.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--data-size", type=int, default=1)
    parser.add_argument("--degree", type=int, default=4)
    parser.add_argument("--traffic-pattern", default="allreduce", choices=["allreduce", "alltoall", "flows"])
    parser.add_argument("--bandwidth", default="100Gbps")
    parser.add_argument("--delay", default="1us")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--summary-name", default="experiment_2_summary.csv")
    parser.add_argument("--memory-profile-name", default="experiment_2_memory_profile.csv")
    parser.add_argument("--object-profile-name", default="experiment_2_object_profile.csv")
    parser.add_argument("--build-profile", default="optimized", choices=["debug", "default", "release", "optimized", "minsizerel"])
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")

    sizes = parse_k_values(args.k_values)
    routings = parse_csv_list(args.routings)
    ns3_tool = pick_ns3_tool(ROOT)

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "results" / f"fattree-memory-profile-{timestamp()}"
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
    memory_profile_path = out_dir / args.memory_profile_name
    object_profile_path = out_dir / args.object_profile_name

    with open(summary_path, "w", newline="", encoding="utf-8") as summary_file, \
         open(memory_profile_path, "w", newline="", encoding="utf-8") as memory_file, \
         open(object_profile_path, "w", newline="", encoding="utf-8") as object_file:
        summary_writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_FIELDS)
        memory_writer = csv.DictWriter(memory_file, fieldnames=MEMORY_PROFILE_FIELDS)
        object_writer = csv.DictWriter(object_file, fieldnames=OBJECT_PROFILE_FIELDS)
        summary_writer.writeheader()
        memory_writer.writeheader()
        object_writer.writeheader()

        total = len(sizes) * len(routings) * args.repeats
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
                        args.degree,
                        args.traffic_pattern,
                    )
                    print(f"[{done}/{total}] {case_id}")
                    rc, wall_s, output = run_logged(cmd, ROOT, log_path)
                    agg = parse_output(output, wall_s)

                    routing_state = find_profile_row(agg, stage="routing_state")
                    topology_build = find_profile_row(agg, stage="topology_build")
                    applications = find_profile_row(agg, stage="applications")
                    object_row = find_object_row(agg, ["post_applications", "post_routing"])

                    init_mem_kb = kb_value(agg.get("init_mem_kb"))
                    exec_mem_kb = kb_value(agg.get("exec_mem_kb"))
                    summary_writer.writerow({
                        "case_id": case_id,
                        "repeat": repeat,
                        "routing": agg.get("routing", routing),
                        "k": size.k,
                        "rc": rc,
                        "init_s": agg.get("init_s", ""),
                        "exec_s": agg.get("exec_s", ""),
                        "wall_s": agg.get("wall_s", wall_s),
                        "init_peak_mem_kb": init_mem_kb,
                        "init_peak_mem_gb": gb_from_kb(init_mem_kb),
                        "exec_peak_mem_kb": exec_mem_kb,
                        "exec_peak_mem_gb": gb_from_kb(exec_mem_kb),
                        "routing_state_delta_kb": routing_state.get("delta_kb", ""),
                        "routing_state_share_pct": routing_state.get("share_pct", ""),
                        "topology_build_delta_kb": topology_build.get("delta_kb", ""),
                        "topology_build_share_pct": topology_build.get("share_pct", ""),
                        "applications_delta_kb": applications.get("delta_kb", ""),
                        "applications_share_pct": applications.get("share_pct", ""),
                        "nodes": object_row.get("nodes", ""),
                        "hosts": agg.get("host_num", ""),
                        "netdevices": object_row.get("netdevices", ""),
                        "channels": object_row.get("channels", ""),
                        "ipv4_interfaces": object_row.get("ipv4_interfaces", ""),
                        "routing_entries": object_row.get("routing_entries", ""),
                        "applications": object_row.get("applications", ""),
                        "config": str(config_path),
                        "log": str(log_path),
                        "cmd": shlex.join(cmd),
                    })

                    summary = agg.get("_memory_profile_summary", {})
                    if not isinstance(summary, dict):
                        summary = {}
                    for row in agg.get("_memory_profile", []):
                        if not isinstance(row, dict):
                            continue
                        memory_writer.writerow({
                            "case_id": case_id,
                            "repeat": repeat,
                            "routing": agg.get("routing", routing),
                            "k": size.k,
                            "stage": row.get("stage", ""),
                            "category": row.get("category", ""),
                            "rss_kb": row.get("rss_kb", ""),
                            "delta_kb": row.get("delta_kb", ""),
                            "share_pct": row.get("share_pct", ""),
                            "detail": row.get("detail", ""),
                            "pid": summary.get("pid", ""),
                            "start_rss_kb": summary.get("start_rss", ""),
                            "final_rss_kb": summary.get("final_rss", ""),
                            "total_delta_kb": summary.get("total_delta", ""),
                            "positive_delta_kb": summary.get("positive_delta", ""),
                            "samples": summary.get("samples", ""),
                        })

                    for row in agg.get("_object_profile", []):
                        if not isinstance(row, dict):
                            continue
                        object_writer.writerow({
                            "case_id": case_id,
                            "repeat": repeat,
                            "routing": agg.get("routing", routing),
                            "k": size.k,
                            "stage": row.get("stage", ""),
                            "levels": row.get("levels", ""),
                            "nodes": row.get("nodes", ""),
                            "netdevices": row.get("netdevices", ""),
                            "p2p_netdevices": row.get("p2p_netdevices", ""),
                            "channels": row.get("channels", ""),
                            "ipv4": row.get("ipv4", ""),
                            "ipv4_interfaces": row.get("ipv4_interfaces", ""),
                            "routing_protocols": row.get("routing_protocols", ""),
                            "rule_based_protocols": row.get("rule_based_protocols", ""),
                            "node_bfs_protocols": row.get("node_bfs_protocols", ""),
                            "rule_based_rules": row.get("rule_based_rules", ""),
                            "routing_entries": row.get("routing_entries", ""),
                            "applications": row.get("applications", ""),
                        })
                    summary_file.flush()
                    memory_file.flush()
                    object_file.flush()

                    if rc != 0:
                        print(f"[WARN] {case_id} failed with rc={rc}; see {log_path}")

    print(f"[DONE] {out_dir}")
    print(f"  summary: {summary_path}")
    print(f"  memory : {memory_profile_path}")
    print(f"  objects: {object_profile_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
