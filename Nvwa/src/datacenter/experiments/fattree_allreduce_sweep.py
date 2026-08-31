#!/usr/bin/env python3
"""Generate FatTree configs and run collective workload experiments."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional


RE_INIT_TIME = re.compile(r"\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_EXEC_TIME = re.compile(r"\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_INIT_MEM = re.compile(r"\bInitialization\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_EXEC_MEM = re.compile(r"\bExecution\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_ROUTING_STATE = re.compile(
    r"Initialization memory profile:\s*stage=routing_state\b[^\n]*\bdelta=(-?[0-9]+)\s*KB\b",
    re.I,
)
RE_OBJECT_PROFILE = re.compile(r"Initialization object profile:\s*stage=([^\s]+)\s*(.*)$", re.I)
RE_INIT_TIME_PROFILE_SUMMARY = re.compile(r"Initialization time profile summary:\s*(.*)$", re.I)
RE_INIT_TIME_PROFILE = re.compile(r"Initialization time profile:\s*stage=([^\s]+)\s*(.*)$", re.I)
RE_TRAFFIC = re.compile(r"Traffic generated:\s*(.*)$", re.I)
RE_FORWARD = re.compile(r"\bFORWARD_STATS\b(.*)$", re.I)
RE_KV = re.compile(r"\b([A-Za-z_]+)=([^\s]+)\b")

CSV_FIELDS = [
    "k",
    "config",
    "routing",
    "workload",
    "data_size_bytes",
    "rc",
    "wall_s",
    "init_time_s",
    "init_profile_total_s",
    "init_profile_accounted_s",
    "init_profile_other_s",
    "time_config_json_s",
    "time_routing_helper_setup_s",
    "time_template_build_s",
    "time_topology_build_s",
    "time_address_registration_s",
    "time_failure_preapply_s",
    "time_routing_computation_s",
    "time_failure_scheduling_s",
    "time_random_failure_events_s",
    "time_debug_trace_registration_s",
    "time_traffic_generation_s",
    "time_application_setup_s",
    "time_other_s",
    "init_peak_kb",
    "routing_state_delta_kb",
    "routing_entries",
    "rule_based_rules",
    "applications",
    "exec_time_s",
    "exec_peak_kb",
    "generated_pattern",
    "generated_flows",
    "logical_steps",
    "chunk_bytes",
    "aggregated_bytes",
    "alltoall_pattern",
    "source_batch_size",
    "source_batches",
    "batch_gap_s",
    "round_gap_s",
    "forward_count",
    "log",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parse_kv(text: str) -> Dict[str, str]:
    return {k: v.rstrip(",") for k, v in RE_KV.findall(text)}


def first_group(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else ""


def generate_fattree_config(k: int, bandwidth: str, delay: str, out_dir: Path) -> Path:
    if k <= 0 or k % 2 != 0:
        raise ValueError(f"FatTree k must be a positive even integer, got {k}")

    hosts_per_switch = k // 2
    aggs_per_pod = k // 2
    edges_per_pod = k // 2
    core_group_num = k // 2
    core_switches = core_group_num * core_group_num

    config = {
        "routing": "RuleBased",
        "link": {
            "bandwidth": bandwidth,
            "delay": delay,
        },
        "levels": [
            {
                "dims": [
                    {
                        "template": "ClosInterLevel",
                        "nodeNum": 1,
                        "subBlockNum": hosts_per_switch,
                        "groupNum": 1,
                    }
                ]
            },
            {
                "dims": [
                    {
                        "template": "ClosInterLevel",
                        "nodeNum": aggs_per_pod,
                        "subBlockNum": edges_per_pod,
                        "groupNum": 1,
                    }
                ]
            },
            {
                "dims": [
                    {
                        "template": "ClosInterLevel",
                        "nodeNum": core_switches,
                        "subBlockNum": k,
                        "groupNum": core_group_num,
                    }
                ]
            },
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_bw = bandwidth.replace("/", "_")
    safe_delay = delay.replace("/", "_")
    path = out_dir / f"fattree_k{k}_{safe_bw}_{safe_delay}.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


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


def parse_metrics(stdout: str) -> Dict[str, str]:
    result: Dict[str, str] = {
        "init_time_s": first_group(RE_INIT_TIME, stdout),
        "exec_time_s": first_group(RE_EXEC_TIME, stdout),
        "init_peak_kb": first_group(RE_INIT_MEM, stdout),
        "exec_peak_kb": first_group(RE_EXEC_MEM, stdout),
        "routing_state_delta_kb": first_group(RE_ROUTING_STATE, stdout),
    }

    profiles: Dict[str, Dict[str, str]] = {}
    time_summary: Dict[str, str] = {}
    time_profiles: Dict[str, Dict[str, str]] = {}
    traffic: Dict[str, str] = {}
    forward: Dict[str, str] = {}
    for line in stdout.splitlines():
        profile_match = RE_OBJECT_PROFILE.search(line)
        if profile_match:
            profiles[profile_match.group(1)] = parse_kv(profile_match.group(2))
            continue
        time_summary_match = RE_INIT_TIME_PROFILE_SUMMARY.search(line)
        if time_summary_match:
            time_summary = parse_kv(time_summary_match.group(1))
            continue
        time_profile_match = RE_INIT_TIME_PROFILE.search(line)
        if time_profile_match:
            time_profiles[time_profile_match.group(1)] = parse_kv(time_profile_match.group(2))
            continue
        traffic_match = RE_TRAFFIC.search(line)
        if traffic_match:
            traffic = parse_kv(traffic_match.group(1))
            continue
        forward_match = RE_FORWARD.search(line)
        if forward_match:
            forward = parse_kv(forward_match.group(1))

    post_routing = profiles.get("post_routing", {})
    post_apps = profiles.get("post_applications", {})
    result.update(
        {
            "init_profile_total_s": time_summary.get("total_s", ""),
            "init_profile_accounted_s": time_summary.get("accounted_s", ""),
            "init_profile_other_s": time_summary.get("other_s", ""),
            "time_config_json_s": time_profiles.get("config_json", {}).get("duration_s", ""),
            "time_routing_helper_setup_s": time_profiles.get("routing_helper_setup", {}).get("duration_s", ""),
            "time_template_build_s": time_profiles.get("template_build", {}).get("duration_s", ""),
            "time_topology_build_s": time_profiles.get("topology_build", {}).get("duration_s", ""),
            "time_address_registration_s": time_profiles.get("address_registration", {}).get("duration_s", ""),
            "time_failure_preapply_s": time_profiles.get("failure_preapply", {}).get("duration_s", ""),
            "time_routing_computation_s": time_profiles.get("routing_computation", {}).get("duration_s", ""),
            "time_failure_scheduling_s": time_profiles.get("failure_scheduling", {}).get("duration_s", ""),
            "time_random_failure_events_s": time_profiles.get("random_failure_events", {}).get("duration_s", ""),
            "time_debug_trace_registration_s": time_profiles.get("debug_trace_registration", {}).get("duration_s", ""),
            "time_traffic_generation_s": time_profiles.get("traffic_generation", {}).get("duration_s", ""),
            "time_application_setup_s": time_profiles.get("application_setup", {}).get("duration_s", ""),
            "time_other_s": time_profiles.get("other", {}).get("duration_s", ""),
            "routing_entries": post_routing.get("routing_entries", ""),
            "rule_based_rules": post_routing.get("rule_based_rules", ""),
            "applications": post_apps.get("applications", ""),
            "generated_pattern": traffic.get("pattern", ""),
            "generated_flows": traffic.get("flows", ""),
            "logical_steps": traffic.get("logical_steps", ""),
            "chunk_bytes": traffic.get("chunk_bytes", ""),
            "aggregated_bytes": traffic.get("aggregated_bytes", ""),
            "alltoall_pattern": traffic.get("alltoall_pattern", ""),
            "source_batch_size": traffic.get("source_batch_size", ""),
            "source_batches": traffic.get("source_batches", ""),
            "batch_gap_s": traffic.get("batch_gap_s", ""),
            "round_gap_s": traffic.get("round_gap_s", ""),
            "forward_count": forward.get("count", ""),
        }
    )
    return result


def build_constructor(root: Path) -> None:
    cmd = ["./ns3", "build", "constructor"]
    proc = subprocess.run(cmd, cwd=root, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"constructor build failed with rc={proc.returncode}")


def run_case(
    root: Path,
    constructor_bin: Optional[Path],
    config_path: Path,
    k: int,
    routing: str,
    workload: str,
    data_size: int,
    data_rate: str,
    packet_size: int,
    time_profile: bool,
    memory_profile: bool,
    init_only: bool,
    alltoall_pattern: str,
    alltoall_source_batch_size: int,
    alltoall_batch_gap: float,
    alltoall_batch_gap_unit: str,
    alltoall_round_gap: float,
    alltoall_round_gap_unit: str,
    log_dir: Path,
) -> Dict[str, str]:
    batch_suffix = ""
    if workload == "alltoall":
        batch_suffix = (
            f"_{alltoall_pattern}"
            f"_srcbatch{alltoall_source_batch_size}"
            f"_gap{alltoall_batch_gap:g}{alltoall_batch_gap_unit}"
            f"_roundgap{alltoall_round_gap:g}{alltoall_round_gap_unit}"
        )
    name = f"k{k}_{routing}_{workload}_{data_size}{batch_suffix}"
    log_path = log_dir / f"{name}.log"
    args = [
        f"--config={config_path}",
        f"--routing={routing}",
        f"--trafficPattern={workload}",
        "--trafficReplayMode=batch",
        f"--dataSize={data_size}",
        f"--dataRate={data_rate}",
        f"--packetSize={packet_size}",
        f"--timeProfile={'true' if time_profile else 'false'}",
        f"--initOnly={'true' if init_only else 'false'}",
        f"--alltoallPattern={alltoall_pattern}",
        f"--alltoallSourceBatchSize={alltoall_source_batch_size}",
        f"--alltoallBatchGap={alltoall_batch_gap}",
        f"--alltoallBatchGapUnit={alltoall_batch_gap_unit}",
        f"--alltoallRoundGap={alltoall_round_gap}",
        f"--alltoallRoundGapUnit={alltoall_round_gap_unit}",
        f"--memory={'true' if memory_profile else 'false'}",
    ]
    if constructor_bin:
        cmd = [str(constructor_bin), *args]
    else:
        cmd = ["./ns3", "run", "constructor " + " ".join(args)]

    start = time.time()
    proc = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wall_s = time.time() - start
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text("$ " + " ".join(cmd) + "\n\n" + proc.stdout, encoding="utf-8")

    metrics = parse_metrics(proc.stdout)
    row = {
        "k": str(k),
        "config": str(config_path),
        "routing": routing,
        "workload": workload,
        "data_size_bytes": str(data_size),
        "rc": str(proc.returncode),
        "wall_s": f"{wall_s:.6f}",
        "log": str(log_path),
    }
    row.update(metrics)
    return row


def write_rows(csv_path: Path, rows: Iterable[Dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def load_completed(csv_path: Path) -> set[tuple[int, str, str, str]]:
    if not csv_path.exists():
        return set()
    completed: set[tuple[int, str, str, str]] = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("rc") != "0":
                continue
            try:
                completed.add((int(row["k"]), row["routing"], row["workload"], row.get("alltoall_pattern", "")))
            except Exception:
                continue
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ks", nargs="+", type=int, default=[8, 16, 24, 32])
    parser.add_argument("--routings", nargs="+", default=["RuleBased", "NodeBfs"])
    parser.add_argument("--workloads", nargs="+", default=["allreduce"], choices=["allreduce", "alltoall"])
    parser.add_argument("--data-size", type=int, default=1048576)
    parser.add_argument("--data-rate", default="100Gbps")
    parser.add_argument("--bandwidth", default="100Gbps")
    parser.add_argument("--delay", default="1us")
    parser.add_argument("--packet-size", type=int, default=1000)
    parser.add_argument("--time-profile", action="store_true")
    parser.add_argument("--no-memory-profile", action="store_true")
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--alltoall-pattern", default="sequential", choices=["sequential", "round_robin"])
    parser.add_argument("--alltoall-source-batch-size", type=int, default=0)
    parser.add_argument("--alltoall-batch-gap", type=float, default=0.0)
    parser.add_argument("--alltoall-batch-gap-unit", default="us", choices=["s", "ms", "us", "ns"])
    parser.add_argument("--alltoall-round-gap", type=float, default=0.0)
    parser.add_argument("--alltoall-round-gap-unit", default="us", choices=["s", "ms", "us", "ns"])
    parser.add_argument("--build-profile", default="optimized")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--output-dir",
        default="results/fattree_allreduce_sweep",
        help="Output directory relative to repo root unless absolute",
    )
    parser.add_argument("--summary-name", default="experiment_1.csv", help="Output CSV file name.")
    args = parser.parse_args()

    root = repo_root()
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    config_dir = out_dir / "generated_configs"
    log_dir = out_dir / "logs"
    csv_path = out_dir / args.summary_name

    if not args.skip_build:
        build_constructor(root)

    constructor_bin = pick_constructor_binary(root, args.build_profile)
    completed = load_completed(csv_path) if args.resume else set()
    rows: List[Dict[str, str]] = []
    if args.resume and csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))

    for k in args.ks:
        config_path = generate_fattree_config(k, args.bandwidth, args.delay, config_dir)
        for workload in args.workloads:
            for routing in args.routings:
                completed_pattern = args.alltoall_pattern if workload == "alltoall" else ""
                if (k, routing, workload, completed_pattern) in completed:
                    print(f"SKIP k={k} workload={workload} routing={routing} (already complete)")
                    continue
                print(f"START k={k} workload={workload} routing={routing}")
                row = run_case(
                    root=root,
                    constructor_bin=constructor_bin,
                    config_path=config_path,
                    k=k,
                    routing=routing,
                    workload=workload,
                    data_size=args.data_size,
                    data_rate=args.data_rate,
                    packet_size=args.packet_size,
                    time_profile=args.time_profile,
                    memory_profile=not args.no_memory_profile,
                    init_only=args.init_only,
                    alltoall_pattern=args.alltoall_pattern,
                    alltoall_source_batch_size=args.alltoall_source_batch_size,
                    alltoall_batch_gap=args.alltoall_batch_gap,
                    alltoall_batch_gap_unit=args.alltoall_batch_gap_unit,
                    alltoall_round_gap=args.alltoall_round_gap,
                    alltoall_round_gap_unit=args.alltoall_round_gap_unit,
                    log_dir=log_dir,
                )
                rows.append(row)
                write_rows(csv_path, rows)
                print(
                    "DONE "
                    f"k={k} workload={workload} routing={routing} rc={row['rc']} "
                    f"init={row.get('init_time_s', '')}s "
                    f"route_mem={row.get('routing_state_delta_kb', '')}KB "
                    f"init_peak={row.get('init_peak_kb', '')}KB "
                    f"exec={row.get('exec_time_s', '')}s "
                    f"exec_peak={row.get('exec_peak_kb', '')}KB"
                )
                if row["rc"] != "0":
                    print(f"Stopping after failed case; see {row['log']}")
                    return int(row["rc"])

    print(f"CSV {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
