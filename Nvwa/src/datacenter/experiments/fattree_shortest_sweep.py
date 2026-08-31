#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fattree shortest routing sweep (K only, no failure, no non-minimal).

目标：
- Fattree size: K = 8, 16, 24, 32, 40, 48, 56, 64
- 对比：仿真总用时(wall) + 峰值内存(Execution peak memory)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


RE_INIT_TIME = re.compile(r"\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_EXEC_TIME = re.compile(r"\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_ROUTING = re.compile(r"\bRouting algorithm\s*:\s*([^\s]+)\b", re.I)
RE_INIT_MEM = re.compile(r"\bInitialization\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_EXEC_MEM = re.compile(r"\bExecution\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b", re.I)
RE_TRACE_FLOWS = re.compile(r"\bTraffic\s*trace\s*flows\s*:\s*([0-9]+)\b", re.I)
RE_OBJECT_PROFILE = re.compile(r"Initialization object profile:\s*stage=([^\s]+)\s*(.*)$", re.I)
RE_KV_INT = re.compile(r"\b([A-Za-z_]+)=([0-9]+)\b")

CSV_FIELDS = [
    "name",
    "topology",
    "k",
    "routing",
    "rc",
    "traffic_pattern",
    "traffic_replay_mode",
    "packet_size",
    "traffic_trace_flows",
    "nodes",
    "rule_based_rules",
    "routing_entries",
    "applications",
    "init_s",
    "exec_s",
    "wall_s",
    "init_peak_mem_kb",
    "exec_peak_mem_gb",
    "exec_peak_mem_kb",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def flow_size_kb(flow_size: int) -> int:
    size = int(flow_size)
    return max(1, (size + 1023) // 1024)


def default_out_name(function: str, topology: str, routing: str, traffic: str, flow_size: int) -> str:
    size_kb = flow_size_kb(flow_size)
    return f"plots/{function}-{topology}-{routing}-{traffic}-{size_kb}KB.csv"


def default_log_dir(function: str, topology: str, routing: str, traffic: str, flow_size: int) -> str:
    size_kb = flow_size_kb(flow_size)
    return f"results/{function}-{topology}-{routing}-{traffic}-{size_kb}KB-logs"


def append_cmd(log_dir: Path, line: str) -> None:
    ensure_dir(log_dir)
    cmd_log = log_dir / "commands.log"
    with open(cmd_log, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pick_ns3_tool(root: Path) -> Path:
    for name in ("ns3", "ns", "waf"):
        p = root / name
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise SystemExit("未找到构建工具：期望 repo 根目录存在可执行的 ./ns3 或 ./ns 或 ./waf")


def pick_constructor_binary(root: Path, build_profile: str) -> Optional[Path]:
    cand = root / "build" / "src" / "datacenter" / "examples" / f"ns3-dev-constructor-{build_profile}"
    if cand.exists() and os.access(cand, os.X_OK):
        return cand
    ex_dir = root / "build" / "src" / "datacenter" / "examples"
    if ex_dir.exists():
        for p in sorted(ex_dir.glob(f"*constructor*{build_profile}*")):
            if p.is_file() and os.access(p, os.X_OK):
                return p
    return None


def run_logged(cmd: List[str], cwd: Path, log_path: Path) -> int:
    ensure_dir(log_path.parent)
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write("$ " + " ".join(cmd) + "\n")
        lf.flush()
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
            lf.write(line)
        rc = proc.wait()
        lf.write(f"\n[rc={rc}]\n")
    return rc


def ns_configure_and_build(ns_tool: Path, build_profile: str, enable_examples: bool) -> None:
    root = ns_tool.parent
    log = root / "results" / f"build-fattree-shortest-{int(time.time())}.log"
    if ns_tool.name in ("ns3", "ns"):
        cfg = [str(ns_tool), "configure", f"--build-profile={build_profile}"]
        if enable_examples:
            cfg.append("--enable-examples")
        rc = run_logged(cfg, root, log)
        if rc != 0:
            raise SystemExit(f"configure 失败（rc={rc}），详见：{log}")
        rc = run_logged([str(ns_tool), "build"], root, log)
        if rc != 0:
            raise SystemExit(f"build 失败（rc={rc}），详见：{log}")
    else:
        cfg = [str(ns_tool), "configure", f"--build-profile={build_profile}"]
        if enable_examples:
            cfg.append("--enable-examples")
        rc = run_logged(cfg, root, log)
        if rc != 0:
            raise SystemExit(f"waf configure 失败（rc={rc}），详见：{log}")
        rc = run_logged([str(ns_tool), "build"], root, log)
        if rc != 0:
            raise SystemExit(f"waf build 失败（rc={rc}），详见：{log}")


def generate_fattree_json(root: Path, k: int, bandwidth: str, delay: str) -> str:
    bw_clean = bandwidth.replace("Gbps", "g").replace("Mbps", "m").replace("bps", "b")
    delay_clean = delay.replace("us", "u").replace("ns", "n").replace("ms", "m")
    expected = f"fattree_k{k}_{bw_clean}_{delay_clean}.json"
    expected_path = root / "src/datacenter/examples/inputs" / expected
    if expected_path.exists():
        return expected

    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    if not gen.exists():
        raise SystemExit(f"未找到 generator：{gen}")
    cmd = [
        sys.executable,
        str(gen),
        "fattree",
        "--k",
        str(k),
        "--bandwidth",
        bandwidth,
        "--delay",
        delay,
    ]
    log = root / "results" / f"gen-fattree-shortest-k{k}-{int(time.time())}.log"
    rc = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Fattree JSON 失败（k={k}, rc={rc}），详见：{log}")

    # 解析 generator 输出的文件名
    out = log.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if m:
        return m.group(1).strip()

    return expected


@dataclass(frozen=True)
class RunResult:
    k: int
    routing: str
    rc: int
    traffic_pattern: str
    traffic_replay_mode: str
    packet_size: int
    traffic_trace_flows: Optional[int]
    init_s: Optional[float]
    exec_s: Optional[float]
    wall_s: float
    nodes: Optional[int]
    rule_based_rules: Optional[int]
    routing_entries: Optional[int]
    applications: Optional[int]
    init_peak_mem_kb: Optional[int]
    exec_peak_mem_kb: Optional[int]

    @property
    def exec_peak_mem_gb(self) -> Optional[float]:
        if self.exec_peak_mem_kb is None:
            return None
        return self.exec_peak_mem_kb / (1024.0 * 1024.0)


def parse_metrics(stdout: str) -> Dict[str, Any]:
    init_s = float(RE_INIT_TIME.search(stdout).group(1)) if RE_INIT_TIME.search(stdout) else None
    exec_s = float(RE_EXEC_TIME.search(stdout).group(1)) if RE_EXEC_TIME.search(stdout) else None
    routing = RE_ROUTING.search(stdout).group(1) if RE_ROUTING.search(stdout) else None
    init_mem_kb = int(RE_INIT_MEM.search(stdout).group(1)) if RE_INIT_MEM.search(stdout) else None
    exec_mem_kb = int(RE_EXEC_MEM.search(stdout).group(1)) if RE_EXEC_MEM.search(stdout) else None
    trace_flows = int(RE_TRACE_FLOWS.search(stdout).group(1)) if RE_TRACE_FLOWS.search(stdout) else None
    object_profiles: Dict[str, Dict[str, int]] = {}
    for line in stdout.splitlines():
        m = RE_OBJECT_PROFILE.search(line)
        if not m:
            continue
        object_profiles[m.group(1)] = {key: int(value) for key, value in RE_KV_INT.findall(m.group(2))}
    object_profile = object_profiles.get("post_applications") or object_profiles.get("post_routing") or {}
    return {
        "init_s": init_s,
        "exec_s": exec_s,
        "routing": routing,
        "init_mem_kb": init_mem_kb,
        "exec_mem_kb": exec_mem_kb,
        "trace_flows": trace_flows,
        "nodes": object_profile.get("nodes"),
        "rule_based_rules": object_profile.get("rule_based_rules"),
        "routing_entries": object_profile.get("routing_entries"),
        "applications": object_profile.get("applications"),
    }


def run_one_case(
    root: Path,
    ns_tool: Path,
    constructor_bin: Optional[Path],
    config_file: str,
    k: int,
    routing: str,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
    packet_size: int,
    traffic_replay_mode: str,
    traffic_trace: Optional[str],
    traffic_trace_max_flows: int,
    traffic_trace_time_scale: float,
    traffic_start_offset: float,
    traffic_trace_stop_padding: float,
    log_dir: Path,
    attempt: int = 1,
) -> RunResult:
    ensure_dir(log_dir)
    nf_tag = f"-nf{num_flows}" if traffic_pattern == "flows" else ""
    safe = f"ft-shortest-k{k}-{routing.lower()}-{traffic_pattern}{nf_tag}-fs{flow_size}-try{attempt}"
    log_path = log_dir / f"{safe}.log"

    args = [
        f"--config={config_file}",
        f"--routing={routing}",
        f"--trafficPattern={traffic_pattern}",
        f"--flowSize={flow_size}",
        f"--packetSize={packet_size}",
        "--memory=true",
    ]
    if traffic_pattern == "flows":
        args.append(f"--numFlows={num_flows}")
    if traffic_pattern == "trace":
        if not traffic_trace:
            raise SystemExit("--trafficPattern=trace requires --trafficTrace")
        args.extend(
            [
                f"--trafficTrace={traffic_trace}",
                f"--trafficReplayMode={traffic_replay_mode}",
                f"--trafficTraceMaxFlows={traffic_trace_max_flows}",
                f"--trafficTraceTimeScale={traffic_trace_time_scale}",
                f"--trafficStartOffset={traffic_start_offset}",
                f"--trafficTraceStopPadding={traffic_trace_stop_padding}",
            ]
        )
    if constructor_bin is not None:
        cmd = [str(constructor_bin)] + args
    else:
        cmd = [str(ns_tool), "run", "constructor " + " ".join(args)]

    t0 = time.time()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    append_cmd(log_dir, f"[{stamp}] {safe} $ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    out, err = proc.communicate()
    wall = time.time() - t0

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n\n")
        f.write("----- STDOUT -----\n")
        f.write(out)
        f.write("\n----- STDERR -----\n")
        f.write(err)
        f.write(f"\n[rc={proc.returncode}] wall_s={wall:.6f}\n")

    m = parse_metrics(out)
    return RunResult(
        k=k,
        routing=m.get("routing") or routing,
        rc=proc.returncode,
        traffic_pattern=traffic_pattern,
        traffic_replay_mode=traffic_replay_mode if traffic_pattern == "trace" else "",
        packet_size=packet_size,
        traffic_trace_flows=m.get("trace_flows"),
        init_s=m.get("init_s"),
        exec_s=m.get("exec_s"),
        wall_s=wall,
        nodes=m.get("nodes"),
        rule_based_rules=m.get("rule_based_rules"),
        routing_entries=m.get("routing_entries"),
        applications=m.get("applications"),
        init_peak_mem_kb=m.get("init_mem_kb"),
        exec_peak_mem_kb=m.get("exec_mem_kb"),
    )


def ensure_csv_header(out_csv: Path) -> None:
    ensure_dir(out_csv.parent)
    if out_csv.exists() and out_csv.stat().st_size > 0:
        with open(out_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
        rows = _csv_read_rows(out_csv)
        if all(field in header for field in CSV_FIELDS):
            return
        tmp = out_csv.with_suffix(out_csv.suffix + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow(row)
        tmp.replace(out_csv)
        return
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)


def append_one_csv(out_csv: Path, r: RunResult) -> None:
    ensure_csv_header(out_csv)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        name = f"fattree-shortest-k{r.k}-{r.routing.lower()}"
        w.writerow(
            [
                name,
                "fattree",
                r.k,
                r.routing,
                r.rc,
                r.traffic_pattern,
                r.traffic_replay_mode,
                r.packet_size,
                "" if r.traffic_trace_flows is None else str(r.traffic_trace_flows),
                "" if r.nodes is None else str(r.nodes),
                "" if r.rule_based_rules is None else str(r.rule_based_rules),
                "" if r.routing_entries is None else str(r.routing_entries),
                "" if r.applications is None else str(r.applications),
                "" if r.init_s is None else f"{r.init_s:.6f}",
                "" if r.exec_s is None else f"{r.exec_s:.6f}",
                f"{r.wall_s:.6f}",
                "" if r.init_peak_mem_kb is None else str(r.init_peak_mem_kb),
                "" if r.exec_peak_mem_gb is None else f"{r.exec_peak_mem_gb:.6f}",
                "" if r.exec_peak_mem_kb is None else str(r.exec_peak_mem_kb),
            ]
        )
        f.flush()


def _csv_read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            rows: List[Dict[str, str]] = []
            for row in reader:
                if any((v or "").strip() for v in row.values()):
                    rows.append(row)
            return rows
    except Exception:
        return []


def load_completed(out_csv: Path, resume_policy: str, include_routing: bool) -> Set[Tuple[int, str]]:
    completed: Set[Tuple[int, str]] = set()
    for r in _csv_read_rows(out_csv):
        try:
            k = int((r.get("k") or "").strip())
        except Exception:
            continue
        routing = (r.get("routing") or "").strip() if include_routing else ""
        key = (k, routing) if include_routing else (k, "")
        if resume_policy == "skip_any":
            completed.add(key)
            continue
        try:
            rc = int((r.get("rc") or "").strip())
        except Exception:
            rc = None
        if rc == 0:
            completed.add(key)
    return completed


def compact_csv_inplace(out_csv: Path, include_routing: bool) -> None:
    rows = _csv_read_rows(out_csv)
    if not rows:
        return
    header = list(rows[0].keys())
    if "k" not in header:
        return

    latest_any: Dict[Tuple[int, str], Dict[str, str]] = {}
    latest_ok: Dict[Tuple[int, str], Dict[str, str]] = {}
    for r in rows:
        try:
            k = int((r.get("k") or "").strip())
        except Exception:
            continue
        routing = (r.get("routing") or "").strip() if include_routing else ""
        key = (k, routing) if include_routing else (k, "")
        latest_any[key] = r
        try:
            rc = int((r.get("rc") or "").strip())
        except Exception:
            rc = None
        if rc == 0:
            latest_ok[key] = r

    seen: Set[Tuple[int, str]] = set()
    compacted: List[Dict[str, str]] = []
    for r in rows:
        try:
            k = int((r.get("k") or "").strip())
        except Exception:
            continue
        routing = (r.get("routing") or "").strip() if include_routing else ""
        key = (k, routing) if include_routing else (k, "")
        if key in seen:
            continue
        chosen = latest_ok.get(key) or latest_any.get(key)
        if chosen:
            compacted.append(chosen)
            seen.add(key)

    tmp = out_csv.with_suffix(out_csv.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in compacted:
            w.writerow(r)
    tmp.replace(out_csv)


def _float(x: Optional[str]) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _mem_gb_from_row(r: Dict[str, str]) -> Optional[float]:
    v = _float(r.get("exec_peak_mem_gb"))
    if v is not None:
        return v
    v = _float(r.get("exec_peak_mem_kb"))
    if v is not None:
        return v / (1024.0 * 1024.0)
    return None


def _ratio(val: Optional[float], base: Optional[float]) -> Optional[float]:
    if val is None or base is None or base == 0:
        return None
    return val / base


def main() -> int:
    p = argparse.ArgumentParser(description="Fattree shortest routing sweep: wall time + memory")
    p.add_argument("--build-profile", default="optimized", choices=["debug", "optimized", "release"])
    p.add_argument("--skip-build", action="store_true")
    p.add_argument(
        "--routing",
        dest="routings",
        action="append",
        choices=["RuleBased", "NodeBfs", "Global", "NodeBfsStrict", "NodeBfsWithHost"],
        help="可多次指定，例如 --routing NodeBfs --routing RuleBased",
    )
    p.add_argument("--bandwidth", default="100Gbps")
    p.add_argument("--delay", default="1us")
    p.add_argument("--trafficPattern", default="allreduce", choices=["flows", "allreduce", "alltoall", "trace"])
    p.add_argument("--numFlows", type=int, default=10)
    p.add_argument("--flowSize", type=int, default=1048576)  # 1MB
    p.add_argument("--packetSize", type=int, default=1000)
    p.add_argument("--trafficReplayMode", default="onoff", choices=["onoff", "batch"])
    p.add_argument("--trafficTrace", default=None, help="CSV trace for --trafficPattern=trace")
    p.add_argument("--trafficTraceMaxFlows", type=int, default=0, help="0 means all trace flows")
    p.add_argument("--trafficTraceTimeScale", type=float, default=1.0)
    p.add_argument("--trafficStartOffset", type=float, default=1.0)
    p.add_argument("--trafficTraceStopPadding", type=float, default=10.0)
    p.add_argument("--out", default="plots/fattree-shortest-time-mem.csv")
    p.add_argument("--log-dir", default="results/fattree-shortest-logs")
    p.add_argument("--only-k", default=None, help="只跑指定 K（逗号分隔），例如 8,16")
    p.add_argument(
        "--resume-policy",
        default="skip_success",
        choices=["skip_success", "skip_any", "rerun_failed"],
        help="断点续跑策略：skip_success(默认) 仅跳过成功；skip_any 只要出现过就跳过；rerun_failed 重跑失败(等价 skip_success)",
    )
    p.add_argument("--max-retries", type=int, default=3, help="单个 K 遇到非零退出时的最大重试次数")
    p.add_argument("--retry-sleep", type=float, default=0.2, help="失败重试前 sleep 秒数")
    args = p.parse_args()
    if args.trafficPattern == "trace" and not args.trafficTrace:
        p.error("--trafficPattern=trace requires --trafficTrace")

    default_out = "plots/fattree-shortest-time-mem.csv"
    default_log = "results/fattree-shortest-logs"
    base_routing = (args.routings[0] if args.routings else "NodeBfs")
    if args.out == default_out:
        args.out = default_out_name("shortest", "Fattree", base_routing, args.trafficPattern, args.flowSize)
    if args.log_dir == default_log:
        args.log_dir = default_log_dir("shortest", "Fattree", base_routing, args.trafficPattern, args.flowSize)

    root = repo_root()
    ns_tool = pick_ns3_tool(root)
    constructor_bin = pick_constructor_binary(root, args.build_profile)

    if not args.skip_build:
        ns_configure_and_build(ns_tool, args.build_profile, enable_examples=True)

    ks = [8, 16, 24, 32, 40, 48, 56, 64]
    if args.only_k:
        ks = [int(x.strip()) for x in args.only_k.split(",") if x.strip()]

    out_csv = root / args.out
    routings = list(args.routings) if args.routings else [base_routing]
    include_routing = len(routings) > 1
    done = load_completed(out_csv, args.resume_policy, include_routing)

    log_dir = root / args.log_dir
    total = len(ks) * len(routings)
    idx = 0
    for k in ks:
        config = generate_fattree_json(root, k, args.bandwidth, args.delay)
        for routing in routings:
            idx += 1
            key = (k, routing) if include_routing else (k, "")
            if key in done:
                print(f"[SKIP] ({idx}/{total}) k={k} routing={routing} 已完成")
                continue
            print(f"[RUN ] ({idx}/{total}) k={k} routing={routing} config={config}")

            last: Optional[RunResult] = None
            for attempt in range(1, max(1, int(args.max_retries)) + 1):
                r = run_one_case(
                    root=root,
                    ns_tool=ns_tool,
                    constructor_bin=constructor_bin,
                    config_file=config,
                    k=k,
                    routing=routing,
                    traffic_pattern=args.trafficPattern,
                    num_flows=args.numFlows,
                    flow_size=args.flowSize,
                    packet_size=args.packetSize,
                    traffic_replay_mode=args.trafficReplayMode,
                    traffic_trace=args.trafficTrace,
                    traffic_trace_max_flows=args.trafficTraceMaxFlows,
                    traffic_trace_time_scale=args.trafficTraceTimeScale,
                    traffic_start_offset=args.trafficStartOffset,
                    traffic_trace_stop_padding=args.trafficTraceStopPadding,
                    log_dir=log_dir,
                    attempt=attempt,
                )
                last = r
                if r.rc == 0:
                    break
                if attempt < args.max_retries:
                    print(
                        f"[RETRY] k={k} routing={routing} attempt={attempt}/{args.max_retries} rc={r.rc} -> retrying..."
                    )
                    time.sleep(float(args.retry_sleep))

            assert last is not None
            append_one_csv(out_csv, last)
            if last.rc == 0:
                done.add(key)
            print(
                f"[DONE] k={k} routing={routing} rc={last.rc} wall={last.wall_s:.2f}s"
                + (f" mem={last.exec_peak_mem_gb:.3f}GB" if last.exec_peak_mem_gb is not None else "")
            )

    compact_csv_inplace(out_csv, include_routing)
    print(f"[OUT ] {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
