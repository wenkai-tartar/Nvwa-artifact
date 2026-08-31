#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fattree failure sweep (K × failure rate) for src/datacenter.

目标：
- failure rate: 0.001, 0.01, 0.1
- Fattree size: K = 8, 16, 24, 32, 40, 48, 56, 64
- 对比：仿真总用时(wall) + 峰值内存(Max RSS)

实现说明：
- 拓扑 JSON 通过 src/datacenter/examples/inputs/topology_generator.py 生成到 inputs/ 目录。
- 仿真程序使用 examples/constructor（支持 --randomFailureRate）。
- macOS: 使用 /usr/bin/time -l 解析 “maximum resident set size”（字节）。
- 解析 constructor 输出的 Initialization time / Execution time（秒）。
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
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
RE_FAILURE_STATS = re.compile(
    r"\bFAILURE_UPDATE_STATS\b.*\bcount=(?P<count>\d+)\b.*\btotal_s=(?P<total>[0-9]+(?:\.[0-9]+)?)\b"
    r".*\bp90_s=(?P<p90>[0-9]+(?:\.[0-9]+)?)\b.*\bp95_s=(?P<p95>[0-9]+(?:\.[0-9]+)?)\b"
    r".*\bp99_s=(?P<p99>[0-9]+(?:\.[0-9]+)?)\b",
    re.I,
)
RE_BFS_TIME = re.compile(r"\bBFS\s+routing\s+time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.I)
RE_FAILURE_FORWARD_TRIE = re.compile(
    r"\bFAILURE_FORWARD_EXCEPTION_TRIE\b.*\btotal_s=(?P<total>[0-9]+(?:\.[0-9]+)?)\b",
    re.I,
)
RE_FORWARD_STATS = re.compile(
    r"\bFORWARD_STATS\b.*\brouting=(?P<routing>[^\s]+)\b.*\bcount=(?P<count>\d+)\b"
    r".*\btotal_s=(?P<total>[0-9]+(?:\.[0-9]+)?)\b.*\bavg_s=(?P<avg>[0-9]+(?:\.[0-9]+)?)\b",
    re.I,
)

CSV_HEADER = [
    "name",
    "topology",
    "k",
    "failure_rate",
    "routing",
    "rc",
    "init_s",
    "exec_s",
    "bfs_routing_s",
    "wall_s",
    "exec_peak_mem_gb",
    "exec_peak_mem_bytes",
    "failure_update_count",
    "failure_update_total_s",
    "failure_update_p90_s",
    "failure_update_p95_s",
    "failure_update_p99_s",
    "failure_forward_exc_trie_total_s",
    "forward_lookup_count",
    "forward_lookup_total_s",
    "forward_lookup_avg_s",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def pick_ns3_tool(root: Path) -> Path:
    for name in ("ns3", "ns", "waf"):
        p = root / name
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise SystemExit("未找到构建工具：期望 repo 根目录存在可执行的 ./ns3 或 ./ns 或 ./waf")


def pick_constructor_binary(root: Path, build_profile: str) -> Optional[Path]:
    """
    Prefer running the compiled binary directly instead of `./ns3 run ...`.
    On some macOS setups, `./ns3 run` wrapper may mis-report signals even when the binary exits 0.
    """
    # Common location for ns-3 cmake builds in this repo.
    cand = root / "build" / "src" / "datacenter" / "examples" / f"ns3-dev-constructor-{build_profile}"
    if cand.exists() and os.access(cand, os.X_OK):
        return cand
    # Fallback: search by pattern under build tree.
    ex_dir = root / "build" / "src" / "datacenter" / "examples"
    if ex_dir.exists():
        for p in sorted(ex_dir.glob(f"*constructor*{build_profile}*")):
            if p.is_file() and os.access(p, os.X_OK):
                return p
    return None


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


def run_logged(cmd: List[str], cwd: Path, log_path: Path) -> Tuple[int, str]:
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
        out_lines: List[str] = []
        for line in proc.stdout:
            lf.write(line)
            out_lines.append(line)
        rc = proc.wait()
        lf.write(f"\n[rc={rc}]\n")
    return rc, "".join(out_lines)


def ns_configure_and_build(ns_tool: Path, build_profile: str, enable_examples: bool) -> None:
    # ns3/ns: ./ns3 configure/build
    # waf: ./waf configure/build
    root = ns_tool.parent
    log = root / "results" / f"build-fattree-failure-{int(time.time())}.log"
    if ns_tool.name in ("ns3", "ns"):
        cfg = [str(ns_tool), "configure", f"--build-profile={build_profile}"]
        if enable_examples:
            cfg.append("--enable-examples")
        rc, _ = run_logged(cfg, root, log)
        if rc != 0:
            raise SystemExit(f"configure 失败（rc={rc}），详见：{log}")
        rc, _ = run_logged([str(ns_tool), "build"], root, log)
        if rc != 0:
            raise SystemExit(f"build 失败（rc={rc}），详见：{log}")
    else:
        cfg = [str(ns_tool), "configure", f"--build-profile={build_profile}"]
        if enable_examples:
            cfg.append("--enable-examples")
        rc, _ = run_logged(cfg, root, log)
        if rc != 0:
            raise SystemExit(f"waf configure 失败（rc={rc}），详见：{log}")
        rc, _ = run_logged([str(ns_tool), "build"], root, log)
        if rc != 0:
            raise SystemExit(f"waf build 失败（rc={rc}），详见：{log}")


def generate_fattree_json(root: Path, k: int, bandwidth: str, delay: str) -> str:
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
    log = root / "results" / f"gen-fattree-k{k}-{int(time.time())}.log"
    rc, out = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Fattree JSON 失败（k={k}, rc={rc}），详见：{log}")

    # generator 会输出 "Output file: <filename>"；也可以根据命名规则推导
    # 我们优先解析输出；解析不到则 fallback 到惯例：fattree_k{k}_<bw>_<delay>.json
    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if m:
        return m.group(1).strip()

    # fallback：与 topology_generator.py 的清洗规则对齐
    bw_clean = bandwidth.replace("Gbps", "g").replace("Mbps", "m").replace("bps", "b")
    delay_clean = delay.replace("us", "u").replace("ns", "n").replace("ms", "m")
    return f"fattree_k{k}_{bw_clean}_{delay_clean}.json"


@dataclass(frozen=True)
class RunResult:
    k: int
    failure_rate: float
    routing: str
    rc: int
    init_s: Optional[float]
    exec_s: Optional[float]
    bfs_routing_s: Optional[float]
    failure_update_count: Optional[int]
    failure_update_total_s: Optional[float]
    failure_update_p90_s: Optional[float]
    failure_update_p95_s: Optional[float]
    failure_update_p99_s: Optional[float]
    failure_forward_exc_trie_total_s: Optional[float]
    forward_lookup_count: Optional[int]
    forward_lookup_total_s: Optional[float]
    forward_lookup_avg_s: Optional[float]
    wall_s: float
    max_rss_bytes: Optional[int]

    @property
    def max_rss_gb(self) -> Optional[float]:
        if self.max_rss_bytes is None:
            return None
        return self.max_rss_bytes / (1024.0 ** 3)


def parse_constructor_metrics(stdout: str) -> Dict[str, Optional[float]]:
    init_s = None
    exec_s = None
    if (m := RE_INIT_TIME.search(stdout)):
        init_s = float(m.group(1))
    if (m := RE_EXEC_TIME.search(stdout)):
        exec_s = float(m.group(1))
    routing = None
    if (m := RE_ROUTING.search(stdout)):
        routing = m.group(1)
    init_mem_kb = None
    exec_mem_kb = None
    if (m := RE_INIT_MEM.search(stdout)):
        init_mem_kb = float(m.group(1))
    if (m := RE_EXEC_MEM.search(stdout)):
        exec_mem_kb = float(m.group(1))
    bfs_routing_s = None
    if (m := RE_BFS_TIME.search(stdout)):
        bfs_routing_s = float(m.group(1))
    failure_count = None
    failure_total_s = None
    failure_p90_s = None
    failure_p95_s = None
    failure_p99_s = None
    if (m := RE_FAILURE_STATS.search(stdout)):
        failure_count = int(m.group("count"))
        failure_total_s = float(m.group("total"))
        failure_p90_s = float(m.group("p90"))
        failure_p95_s = float(m.group("p95"))
        failure_p99_s = float(m.group("p99"))
    failure_forward_exc_trie_total_s = None
    if (m := RE_FAILURE_FORWARD_TRIE.search(stdout)):
        failure_forward_exc_trie_total_s = float(m.group("total"))
    forward_count = None
    forward_total_s = None
    forward_avg_s = None
    for m in RE_FORWARD_STATS.finditer(stdout):
        forward_count = int(m.group("count"))
        forward_total_s = float(m.group("total"))
        forward_avg_s = float(m.group("avg"))
    return {
        "init_s": init_s,
        "exec_s": exec_s,
        "routing": routing,
        "init_mem_kb": init_mem_kb,
        "exec_mem_kb": exec_mem_kb,
        "bfs_routing_s": bfs_routing_s,
        "failure_update_count": failure_count,
        "failure_update_total_s": failure_total_s,
        "failure_update_p90_s": failure_p90_s,
        "failure_update_p95_s": failure_p95_s,
        "failure_update_p99_s": failure_p99_s,
        "failure_forward_exc_trie_total_s": failure_forward_exc_trie_total_s,
        "forward_lookup_count": forward_count,
        "forward_lookup_total_s": forward_total_s,
        "forward_lookup_avg_s": forward_avg_s,
    }


def run_one_case(
    root: Path,
    ns_tool: Path,
    constructor_bin: Optional[Path],
    config_file: str,
    k: int,
    failure_rate: float,
    routing: str,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
    random_failure_time: float,
    random_failure_time_unit: str,
    random_failure_seed: int,
    log_dir: Path,
    random_failure_rate: Optional[float] = None,
    failure_config: Optional[str] = None,
    failure_pre_apply: bool = False,
    random_failure_out: Optional[str] = None,
    attempt: int = 1,
) -> RunResult:
    """
    执行一次 ./ns3 run constructor ... 并采集：
    - init/exec 时间：从 stdout 解析
    - wall 时间：python 计时
    - Max RSS：从 /usr/bin/time 输出解析
    """
    ensure_dir(log_dir)

    rate = failure_rate if random_failure_rate is None else random_failure_rate
    prog_parts = [
        f"--routing={routing}",
        f"--trafficPattern={traffic_pattern}",
        f"--flowSize={flow_size}",
        f"--randomFailureRate={rate}",
        f"--randomFailureTime={random_failure_time}",
        f"--randomFailureTimeUnit={random_failure_time_unit}",
        f"--randomFailureSeed={random_failure_seed}",
        "--memory=true",
    ]
    if traffic_pattern == "flows":
        prog_parts.append(f"--numFlows={num_flows}")
    if failure_config:
        prog_parts.append(f"--failure={failure_config}")
    if failure_pre_apply:
        prog_parts.append("--failurePreApply=true")
    if random_failure_out:
        prog_parts.append(f"--randomFailureOut={random_failure_out}")

    # NOTE:
    # - Do NOT use /usr/bin/time -l on macOS here (may crash with SIGSEGV in some environments).
    # - Prefer running the built constructor binary directly to avoid wrapper issues.
    if constructor_bin is not None:
        cmd = [
            str(constructor_bin),
            f"--config={config_file}",
        ] + prog_parts
    else:
        cmd = [str(ns_tool), "run", f"constructor --config={config_file} " + " ".join(prog_parts)]

    nf_tag = f"-nf{num_flows}" if traffic_pattern == "flows" else ""
    safe = f"ft-k{k}-fr{failure_rate:g}-{routing.lower()}-{traffic_pattern}{nf_tag}-fs{flow_size}-try{attempt}"
    log_path = log_dir / f"{safe}.log"

    t0 = time.time()
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

    m = parse_constructor_metrics(out)
    exec_mem_kb = m.get("exec_mem_kb")
    max_rss = int(exec_mem_kb * 1024) if isinstance(exec_mem_kb, (int, float)) else None
    return RunResult(
        k=k,
        failure_rate=failure_rate,
        routing=m.get("routing") or routing,
        rc=proc.returncode,
        init_s=m.get("init_s"),
        exec_s=m.get("exec_s"),
        bfs_routing_s=m.get("bfs_routing_s"),
        failure_update_count=m.get("failure_update_count"),
        failure_update_total_s=m.get("failure_update_total_s"),
        failure_update_p90_s=m.get("failure_update_p90_s"),
        failure_update_p95_s=m.get("failure_update_p95_s"),
        failure_update_p99_s=m.get("failure_update_p99_s"),
        failure_forward_exc_trie_total_s=m.get("failure_forward_exc_trie_total_s"),
        forward_lookup_count=m.get("forward_lookup_count"),
        forward_lookup_total_s=m.get("forward_lookup_total_s"),
        forward_lookup_avg_s=m.get("forward_lookup_avg_s"),
        wall_s=wall,
        max_rss_bytes=max_rss,
    )


def write_raw_csv(path: Path, rows: List[RunResult]) -> None:
    ensure_dir(path.parent)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in rows:
            name = f"fattree-failure-ft-k{r.k}-fr{r.failure_rate:g}-{r.routing.lower()}"
            w.writerow(
                [
                    name,
                    "fattree",
                    r.k,
                    r.failure_rate,
                    r.routing,
                    r.rc,
                    "" if r.init_s is None else f"{r.init_s:.6f}",
                    "" if r.exec_s is None else f"{r.exec_s:.6f}",
                    "" if r.bfs_routing_s is None else f"{r.bfs_routing_s:.6f}",
                    f"{r.wall_s:.6f}",
                    "" if r.max_rss_gb is None else f"{r.max_rss_gb:.6f}",
                    "" if r.max_rss_bytes is None else str(r.max_rss_bytes),
                    "" if r.failure_update_count is None else str(r.failure_update_count),
                    "" if r.failure_update_total_s is None else f"{r.failure_update_total_s:.6f}",
                    "" if r.failure_update_p90_s is None else f"{r.failure_update_p90_s:.6f}",
                    "" if r.failure_update_p95_s is None else f"{r.failure_update_p95_s:.6f}",
                    "" if r.failure_update_p99_s is None else f"{r.failure_update_p99_s:.6f}",
                    "" if r.failure_forward_exc_trie_total_s is None else f"{r.failure_forward_exc_trie_total_s:.6f}",
                    "" if r.forward_lookup_count is None else str(r.forward_lookup_count),
                    "" if r.forward_lookup_total_s is None else f"{r.forward_lookup_total_s:.6f}",
                    "" if r.forward_lookup_avg_s is None else f"{r.forward_lookup_avg_s:.9f}",
                ]
            )


def _csv_read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            out: List[Dict[str, str]] = []
            for row in reader:
                # 跳过空行
                if any((v or "").strip() for v in row.values()):
                    out.append(row)
            return out
    except Exception:
        # 文件可能被中断写入导致损坏；这里不让脚本直接挂掉
        return []


def _float_or_none(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _int_or_none(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def load_completed_keys(out_csv: Path, resume_policy: str) -> Set[Tuple[int, float, str]]:
    """
    返回已完成的 (k, failure_rate, routing) key 集合。
    resume_policy:
      - skip_success: 仅跳过 rc==0 的项（默认，推荐）
      - skip_any:     只要 CSV 里出现过就跳过
      - rerun_failed: 仅跳过成功；失败会重跑（等价 skip_success）
    """
    completed: Set[Tuple[int, float, str]] = set()
    for r in _csv_read_rows(out_csv):
        k = _int_or_none(r.get("k"))
        fr = _float_or_none(r.get("failure_rate"))
        routing = (r.get("routing") or "").strip()
        rc = _int_or_none(r.get("rc"))
        if k is None or fr is None or not routing:
            continue
        if resume_policy == "skip_any":
            completed.add((k, fr, routing))
        else:
            if rc == 0:
                completed.add((k, fr, routing))
    return completed


def ensure_csv_header(out_csv: Path) -> None:
    ensure_dir(out_csv.parent)
    if not out_csv.exists() or out_csv.stat().st_size == 0:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADER)
        return

    with open(out_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            existing_rows: List[Dict[str, str]] = []
        else:
            existing_rows = list(reader)
        existing_header = reader.fieldnames or []

    if existing_header == CSV_HEADER:
        return

    # Migrate to the new header (fill missing fields with empty strings).
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for row in existing_rows:
            out_row = {k: row.get(k, "") for k in CSV_HEADER}
            w.writerow(out_row)


def append_one_csv(out_csv: Path, r: RunResult) -> None:
    ensure_csv_header(out_csv)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        name = f"fattree-failure-ft-k{r.k}-fr{r.failure_rate:g}-{r.routing.lower()}"
        w.writerow(
            [
                name,
                "fattree",
                r.k,
                r.failure_rate,
                r.routing,
                r.rc,
                "" if r.init_s is None else f"{r.init_s:.6f}",
                "" if r.exec_s is None else f"{r.exec_s:.6f}",
                "" if r.bfs_routing_s is None else f"{r.bfs_routing_s:.6f}",
                f"{r.wall_s:.6f}",
                "" if r.max_rss_gb is None else f"{r.max_rss_gb:.6f}",
                "" if r.max_rss_bytes is None else str(r.max_rss_bytes),
                "" if r.failure_update_count is None else str(r.failure_update_count),
                "" if r.failure_update_total_s is None else f"{r.failure_update_total_s:.6f}",
                "" if r.failure_update_p90_s is None else f"{r.failure_update_p90_s:.6f}",
                "" if r.failure_update_p95_s is None else f"{r.failure_update_p95_s:.6f}",
                "" if r.failure_update_p99_s is None else f"{r.failure_update_p99_s:.6f}",
                "" if r.failure_forward_exc_trie_total_s is None else f"{r.failure_forward_exc_trie_total_s:.6f}",
                "" if r.forward_lookup_count is None else str(r.forward_lookup_count),
                "" if r.forward_lookup_total_s is None else f"{r.forward_lookup_total_s:.6f}",
                "" if r.forward_lookup_avg_s is None else f"{r.forward_lookup_avg_s:.9f}",
            ]
        )
        f.flush()


def compact_csv_inplace(out_csv: Path) -> None:
    """
    去重压缩 CSV，避免断点续跑导致同一组 (k,failure_rate,routing) 多次写入。
    规则：
    - key: (k, failure_rate, routing)
    - 若某 key 有成功(rc==0)记录，则保留最后一条成功记录
    - 否则保留最后一条记录（失败）
    """
    rows = _csv_read_rows(out_csv)
    if not rows:
        return

    header = list(rows[0].keys())
    if not header or "k" not in header or "failure_rate" not in header or "routing" not in header:
        return

    latest_any: Dict[Tuple[int, float, str], Dict[str, str]] = {}
    latest_ok: Dict[Tuple[int, float, str], Dict[str, str]] = {}

    for r in rows:
        k = _int_or_none(r.get("k"))
        fr = _float_or_none(r.get("failure_rate"))
        routing = (r.get("routing") or "").strip()
        rc = _int_or_none(r.get("rc"))
        if k is None or fr is None or not routing:
            continue
        key = (k, fr, routing)
        latest_any[key] = r
        if rc == 0:
            latest_ok[key] = r

    # 以原文件出现顺序为准输出（保证更稳定的可读性）
    seen: Set[Tuple[int, float, str]] = set()
    compacted: List[Dict[str, str]] = []
    for r in rows:
        k = _int_or_none(r.get("k"))
        fr = _float_or_none(r.get("failure_rate"))
        routing = (r.get("routing") or "").strip()
        if k is None or fr is None or not routing:
            continue
        key = (k, fr, routing)
        if key in seen:
            continue
        chosen = latest_ok.get(key) or latest_any.get(key)
        if chosen is None:
            continue
        compacted.append(chosen)
        seen.add(key)

    tmp = out_csv.with_suffix(out_csv.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in compacted:
            w.writerow(r)
    tmp.replace(out_csv)


def main() -> int:
    p = argparse.ArgumentParser(description="Fattree failure sweep: wall time + Max RSS")
    p.add_argument("--build-profile", default="optimized", choices=["debug", "optimized", "release"])
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--routing", default="RuleBased", choices=["RuleBased", "NodeBfs", "Global", "NodeBfsStrict", "NodeBfsWithHost"])
    p.add_argument("--bfs-routing", default="NodeBfs", choices=["NodeBfs", "NodeBfsStrict", "NodeBfsWithHost"])
    p.add_argument("--no-bfs", action="store_true", help="只运行 RuleBased，不跑 BFS")
    p.add_argument("--bandwidth", default="100Gbps")
    p.add_argument("--delay", default="1us")
    p.add_argument("--trafficPattern", default="allreduce", choices=["flows", "allreduce", "alltoall"])
    p.add_argument("--numFlows", type=int, default=10)
    p.add_argument("--flowSize", type=int, default=1048576)  # 1MB
    p.add_argument("--randomFailureTime", type=float, default=0.5)
    p.add_argument("--randomFailureTimeUnit", default="s", choices=["s", "ms", "us", "ns"])
    p.add_argument("--randomFailureSeed", type=int, default=1)
    p.add_argument("--failure-json-dir", default="results/failure-json")
    p.add_argument("--out", default="plots/fattree-failure-time-mem.csv")
    p.add_argument("--log-dir", default="results/fattree-failure-logs")
    p.add_argument("--only-k", default=None, help="只跑指定 K（逗号分隔），例如 8,16")
    p.add_argument("--only-fr", default=None, help="只跑指定 failure rate（逗号分隔），例如 0.001,0.1")
    p.add_argument(
        "--resume-policy",
        default="skip_success",
        choices=["skip_success", "skip_any", "rerun_failed"],
        help="断点续跑策略：skip_success(默认) 仅跳过成功；skip_any 只要出现过就跳过；rerun_failed 重跑失败(等价 skip_success)",
    )
    p.add_argument("--max-retries", type=int, default=3, help="单个组合遇到信号/非零退出时的最大重试次数")
    p.add_argument("--retry-sleep", type=float, default=0.2, help="失败重试前 sleep 秒数（避免瞬时抖动）")
    p.add_argument(
        "--record-failures",
        action="store_true",
        help="将失败/崩溃(run rc!=0 或 signal)也写入 CSV（默认仅写入成功 rc==0）",
    )
    args = p.parse_args()

    default_out = "plots/fattree-failure-time-mem.csv"
    default_log = "results/fattree-failure-logs"
    if args.out == default_out:
        args.out = default_out_name("failure", "Fattree", args.routing, args.trafficPattern, args.flowSize)
    if args.log_dir == default_log:
        args.log_dir = default_log_dir("failure", "Fattree", args.routing, args.trafficPattern, args.flowSize)

    run_bfs = not args.no_bfs
    if run_bfs and args.routing != "RuleBased":
        raise SystemExit("--no-bfs 或将 --routing 设为 RuleBased 后再运行 BFS 对照")

    root = repo_root()
    ns_tool = pick_ns3_tool(root)
    constructor_bin = pick_constructor_binary(root, args.build_profile)
    if constructor_bin is not None:
        print(f"[BIN ] Using constructor binary: {constructor_bin}")
    else:
        print("[BIN ] constructor binary not found; falling back to './ns3 run constructor ...'")

    if not args.skip_build:
        ns_configure_and_build(ns_tool, args.build_profile, enable_examples=True)

    ks = [8, 16, 24, 32, 40, 48, 56, 64]
    frs = [0.001]
    if args.only_k:
        ks = [int(x.strip()) for x in args.only_k.split(",") if x.strip()]
    if args.only_fr:
        frs = [float(x.strip()) for x in args.only_fr.split(",") if x.strip()]

    # 1) 生成拓扑 JSON
    cfg_by_k: Dict[int, str] = {}
    for k in ks:
        cfg_by_k[k] = generate_fattree_json(root, k, args.bandwidth, args.delay)

    # 2) 批量运行
    log_dir = root / args.log_dir
    out_csv = root / args.out
    completed = load_completed_keys(out_csv, args.resume_policy)
    if completed:
        print(f"[RESUME] 已从 {out_csv} 识别到 {len(completed)} 个已完成组合，将自动跳过。")
    rows: List[RunResult] = []
    total = len(ks) * len(frs) * (2 if run_bfs else 1)
    idx = 0
    failure_json_dir = root / args.failure_json_dir
    ensure_dir(failure_json_dir)

    def run_with_retries(**kwargs: Any) -> RunResult:
        last: Optional[RunResult] = None
        max_retries = max(1, int(args.max_retries))
        for attempt in range(1, max_retries + 1):
            r = run_one_case(attempt=attempt, **kwargs)
            last = r
            if r.rc == 0:
                break
            if attempt < max_retries:
                print(
                    f"[RETRY] k={kwargs.get('k')} fr={kwargs.get('failure_rate')} "
                    f"routing={kwargs.get('routing')} attempt={attempt}/{max_retries} rc={r.rc} -> retrying..."
                )
                time.sleep(float(args.retry_sleep))
        assert last is not None
        return last

    for k in ks:
        for fr in frs:
            fr_tag = f"{fr:g}".replace(".", "p")
            failure_file = failure_json_dir / f"auto_ft_k{k}_fr{fr_tag}_seed{args.randomFailureSeed}.json"

            # RuleBased run (generate failure file)
            idx += 1
            rule_key = (k, fr, args.routing)
            need_rule_run = not (rule_key in completed and failure_file.exists())
            rule_result: Optional[RunResult] = None
            if not need_rule_run:
                print(f"[SKIP] ({idx}/{total}) k={k} failure_rate={fr} routing={args.routing} (已完成)")
            else:
                print(f"[RUN ] ({idx}/{total}) k={k} failure_rate={fr} routing={args.routing}")
                rule_result = run_with_retries(
                    root=root,
                    ns_tool=ns_tool,
                    constructor_bin=constructor_bin,
                    config_file=cfg_by_k[k],
                    k=k,
                    failure_rate=fr,
                    routing=args.routing,
                    traffic_pattern=args.trafficPattern,
                    num_flows=args.numFlows,
                    flow_size=args.flowSize,
                    random_failure_time=args.randomFailureTime,
                    random_failure_time_unit=args.randomFailureTimeUnit,
                    random_failure_seed=args.randomFailureSeed,
                    random_failure_out=str(failure_file),
                    log_dir=log_dir,
                )
                rows.append(rule_result)
                if rule_result.rc == 0 or args.record_failures:
                    append_one_csv(out_csv, rule_result)
                if args.resume_policy != "skip_any" and rule_result.rc == 0:
                    completed.add(rule_key)
                print(
                    f"[DONE] k={k} fr={fr} routing={args.routing} rc={rule_result.rc} wall={rule_result.wall_s:.2f}s"
                    + (f" max_rss={rule_result.max_rss_gb:.3f}GB" if rule_result.max_rss_gb is not None else "")
                )

            # BFS run (pre-apply failure file before routing calculation)
            if run_bfs:
                idx += 1
                bfs_key = (k, fr, args.bfs_routing)
                if bfs_key in completed:
                    print(f"[SKIP] ({idx}/{total}) k={k} failure_rate={fr} routing={args.bfs_routing} (已完成)")
                    continue
                if not failure_file.exists():
                    print(
                        f"[SKIP] ({idx}/{total}) k={k} failure_rate={fr} routing={args.bfs_routing} "
                        f"(failure 文件不存在: {failure_file})"
                    )
                    continue
                if rule_result is not None and rule_result.rc != 0:
                    print(
                        f"[SKIP] ({idx}/{total}) k={k} failure_rate={fr} routing={args.bfs_routing} "
                        "(RuleBased 失败，跳过 BFS)"
                    )
                    continue

                print(f"[RUN ] ({idx}/{total}) k={k} failure_rate={fr} routing={args.bfs_routing}")
                bfs_result = run_with_retries(
                    root=root,
                    ns_tool=ns_tool,
                    constructor_bin=constructor_bin,
                    config_file=cfg_by_k[k],
                    k=k,
                    failure_rate=fr,
                    routing=args.bfs_routing,
                    traffic_pattern=args.trafficPattern,
                    num_flows=args.numFlows,
                    flow_size=args.flowSize,
                    random_failure_time=args.randomFailureTime,
                    random_failure_time_unit=args.randomFailureTimeUnit,
                    random_failure_seed=args.randomFailureSeed,
                    random_failure_rate=0.0,
                    failure_config=str(failure_file),
                    failure_pre_apply=True,
                    log_dir=log_dir,
                )
                rows.append(bfs_result)
                if bfs_result.rc == 0 or args.record_failures:
                    append_one_csv(out_csv, bfs_result)
                if args.resume_policy != "skip_any" and bfs_result.rc == 0:
                    completed.add(bfs_key)
                print(
                    f"[DONE] k={k} fr={fr} routing={args.bfs_routing} rc={bfs_result.rc} wall={bfs_result.wall_s:.2f}s"
                    + (f" max_rss={bfs_result.max_rss_gb:.3f}GB" if bfs_result.max_rss_gb is not None else "")
                )

    print(f"[OUT ] {out_csv}")
    # 断点续跑场景下，CSV 可能包含重复组合；收尾做一次去重压缩
    compact_csv_inplace(out_csv)

    # 3) 打印一个简洁的汇总（按 K / failure rate）
    #    只在 stdout 输出；文件里用 CSV 更方便后续处理/画图
    print("\n=== Summary (wall_s / max_rss_gb) ===")
    rows_sorted = sorted(rows, key=lambda x: (x.k, x.failure_rate, x.routing))
    for r in rows_sorted:
        mem = "-" if r.max_rss_gb is None else f"{r.max_rss_gb:.3f}GB"
        print(f"k={r.k:>2} fr={r.failure_rate:g} routing={r.routing}\twall={r.wall_s:.2f}s\tmax_rss={mem}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
