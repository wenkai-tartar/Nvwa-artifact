#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Non-minimal strategy sweep for src/datacenter (time + memory).

实验集合：
1) Dragonfly Valiant: h = 2,4,6,8,10
2) Dragonfly UGAL:   h = 2,4,6,8,10
   - Full-size configs: a = 2p = 2h, p = h, g = a*h + 1 (Absolute)
3) 3D Torus Detour (1 stage): d = 5,10,15,20   (三维均为 d；节点数 d^3)
4) 3D Torus Detour (2 stage): d = 5,10,15,20

输出：
- 默认写到 plots/nonminimal-time-mem.csv
- 每跑完一个 case 立即 append + flush，支持断点续跑（跳过已成功项）
"""

from __future__ import annotations

import argparse
import csv
import json
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
RE_FORWARD_STATS = re.compile(
    r"\bFORWARD_STATS\b.*\brouting=(?P<routing>[^\s]+)\b.*\bcount=(?P<count>\d+)\b"
    r".*\btotal_s=(?P<total>[0-9]+(?:\.[0-9]+)?)\b.*\bavg_s=(?P<avg>[0-9]+(?:\.[0-9]+)?)\b",
    re.I,
)

CSV_HEADER = [
    "case_key",
    "name",
    "group",
    "variant",
    "param_name",
    "param_value",
    "config",
    "routing",
    "rc",
    "init_s",
    "exec_s",
    "wall_s",
    "exec_peak_mem_gb",
    "exec_peak_mem_kb",
    "forward_lookup_count",
    "forward_lookup_total_s",
    "forward_lookup_avg_s",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


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
    root = ns_tool.parent
    log = root / "results" / f"build-nonminimal-{int(time.time())}.log"
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


def generate_dragonfly_json(
    root: Path,
    *,
    h: int,
    algorithm: str,  # "Valiant" or "UGAL"
    bandwidth: str,
    delay: str,
    metric: str,
    transit_fields: str,
    alpha: Optional[float] = None,
    detour_penalty: Optional[float] = None,
) -> str:
    """
    Full-size dragonfly:
      a = 2p = 2h
      p = h
      g = a*h + 1 (Absolute)
    """
    a = 2 * h
    p = h
    g = a * h + 1

    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    if not gen.exists():
        raise SystemExit(f"未找到 generator：{gen}")

    cmd = [
        sys.executable,
        str(gen),
        "dragonfly",
        "--groups",
        str(g),
        "--routers",
        str(a),
        "--hosts",
        str(p),
        "--global-links",
        str(h),
        "--dragonfly-strategy",
        "Absolute",
        "--routing",
        "RuleBased",
        "--bandwidth",
        bandwidth,
        "--delay",
        delay,
        "--nonminimal",
        "--nonminimal-algorithm",
        algorithm,
        "--nonminimal-metric",
        metric,
        "--nonminimal-transit-fields",
        transit_fields,
    ]
    if algorithm.upper() in ("UGAL", "UGAL "):
        if alpha is None:
            alpha = 1.0
        if detour_penalty is None:
            detour_penalty = 1.0
        cmd += ["--nonminimal-alpha", str(alpha)]
        cmd += ["--nonminimal-detour-penalty", str(detour_penalty)]

    log = root / "results" / f"gen-dragonfly-{algorithm.lower()}-h{h}-{int(time.time())}.log"
    rc, out = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Dragonfly JSON 失败（h={h}, rc={rc}），详见：{log}")

    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if not m:
        raise SystemExit(f"无法从 generator 输出解析文件名（h={h}）。详见：{log}")
    return m.group(1).strip()


def _torus_3d_levels_json(d: int) -> str:
    # 3D torus: three TorusIntraLevel dimensions, each subBlockNum = d.
    # nodeNum=0 means "no new nodes, add a new dimension on the current level".
    # Repeating 3 times yields d^3 nodes at level 0.
    levels = [
        {
            "dims": [
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
                {"template": "TorusIntraLevel", "nodeNum": 0, "subBlockNum": d, "LinkArrangement": "SameRank"},
            ]
        }
    ]
    import json as _json

    return _json.dumps(levels, separators=(",", ":"))


def generate_torus_detour_json(
    root: Path,
    *,
    d: int,
    detour_stages: int,  # 1 or 2
    bandwidth: str,
    delay: str,
    metric: str,
    transit_fields: str,
) -> str:
    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    if not gen.exists():
        raise SystemExit(f"未找到 generator：{gen}")

    out_name = f"torus3d_d{d}_detour{detour_stages}.json"
    cmd = [
        sys.executable,
        str(gen),
        "custom",
        "-o",
        out_name,
        "--levels",
        _torus_3d_levels_json(d),
        "--routing",
        "RuleBased",
        "--bandwidth",
        bandwidth,
        "--delay",
        delay,
        "--nonminimal",
        "--nonminimal-algorithm",
        "Detour",
        "--nonminimal-metric",
        metric,
        "--nonminimal-transit-fields",
        transit_fields,
        "--nonminimal-detour-stages",
        str(detour_stages),
    ]
    log = root / "results" / f"gen-torus3d-d{d}-detour{detour_stages}-{int(time.time())}.log"
    rc, out = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Torus JSON 失败（d={d}, stages={detour_stages}, rc={rc}），详见：{log}")

    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if not m:
        # 对 custom 来说，generator 通常会输出 out_name；解析不到就直接用 out_name
        return out_name
    return m.group(1).strip()


def _resolve_config_path(root: Path, config_file: str) -> Path:
    p = Path(config_file)
    if p.is_absolute():
        return p
    if p.parent == Path():
        return root / "src/datacenter/examples/inputs" / p
    return root / p


def ensure_baseline_config(root: Path, config_file: str, suffix: str = "shortest") -> str:
    src = _resolve_config_path(root, config_file)
    if not src.exists():
        raise SystemExit(f"基线配置源文件不存在：{src}")
    dst = src.with_name(f"{src.stem}_{suffix}{src.suffix}")
    with open(src, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "nonMinimal" in cfg:
        del cfg["nonMinimal"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return str(dst)


@dataclass(frozen=True)
class Case:
    group: str          # "dragonfly_valiant" | "dragonfly_ugal" | "torus_detour1" | "torus_detour2"
    param_name: str     # "h" or "d"
    param_value: int
    config_file: str
    routing: str = "RuleBased"
    variant: str = "nonminimal"  # "nonminimal" | "baseline"

    def key(self) -> str:
        return f"{self.group}:{self.param_name}={self.param_value}:{self.variant}"

    def name(self) -> str:
        return f"{self.group}-{self.param_name}{self.param_value}-{self.variant}"


@dataclass(frozen=True)
class Result:
    case_key: str
    name: str
    group: str
    variant: str
    param_name: str
    param_value: int
    config: str
    routing: str
    rc: int
    init_s: Optional[float]
    exec_s: Optional[float]
    wall_s: float
    exec_peak_mem_kb: Optional[int]
    forward_lookup_count: Optional[int]
    forward_lookup_total_s: Optional[float]
    forward_lookup_avg_s: Optional[float]

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
        "forward_lookup_count": forward_count,
        "forward_lookup_total_s": forward_total_s,
        "forward_lookup_avg_s": forward_avg_s,
    }


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

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for row in existing_rows:
            out_row = {k: row.get(k, "") for k in CSV_HEADER}
            w.writerow(out_row)


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


def load_completed(
    out_csv: Path,
    resume_policy: str,
    expected_routing_by_key: Optional[Dict[str, str]] = None,
) -> Set[str]:
    completed: Set[str] = set()
    for r in _csv_read_rows(out_csv):
        key = (r.get("case_key") or "").strip()
        if not key:
            continue
        if expected_routing_by_key is not None:
            expected_routing = (expected_routing_by_key.get(key) or "").strip()
            actual_routing = (r.get("routing") or "").strip()
            if expected_routing and actual_routing != expected_routing:
                continue
        if resume_policy == "skip_any":
            completed.add(key)
            continue
        # skip_success / rerun_failed: only rc==0 counts
        try:
            rc = int((r.get("rc") or "").strip())
        except Exception:
            rc = None
        if rc == 0:
            completed.add(key)
    return completed


def append_one(out_csv: Path, r: Result) -> None:
    ensure_csv_header(out_csv)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                r.case_key,
                r.name,
                r.group,
                r.variant,
                r.param_name,
                r.param_value,
                r.config,
                r.routing,
                r.rc,
                "" if r.init_s is None else f"{r.init_s:.6f}",
                "" if r.exec_s is None else f"{r.exec_s:.6f}",
                f"{r.wall_s:.6f}",
                "" if r.exec_peak_mem_gb is None else f"{r.exec_peak_mem_gb:.6f}",
                "" if r.exec_peak_mem_kb is None else str(r.exec_peak_mem_kb),
                "" if r.forward_lookup_count is None else str(r.forward_lookup_count),
                "" if r.forward_lookup_total_s is None else f"{r.forward_lookup_total_s:.6f}",
                "" if r.forward_lookup_avg_s is None else f"{r.forward_lookup_avg_s:.9f}",
            ]
        )
        f.flush()


def compact_csv_inplace(out_csv: Path) -> None:
    rows = _csv_read_rows(out_csv)
    if not rows:
        return
    header = list(rows[0].keys())
    if "case_key" not in header:
        return

    latest_any: Dict[str, Dict[str, str]] = {}
    latest_ok: Dict[str, Dict[str, str]] = {}
    for r in rows:
        k = (r.get("case_key") or "").strip()
        if not k:
            continue
        latest_any[k] = r
        try:
            rc = int((r.get("rc") or "").strip())
        except Exception:
            rc = None
        if rc == 0:
            latest_ok[k] = r

    seen: Set[str] = set()
    compacted: List[Dict[str, str]] = []
    for r in rows:
        k = (r.get("case_key") or "").strip()
        if not k or k in seen:
            continue
        chosen = latest_ok.get(k) or latest_any.get(k)
        if chosen:
            compacted.append(chosen)
            seen.add(k)

    tmp = out_csv.with_suffix(out_csv.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in compacted:
            w.writerow(r)
    tmp.replace(out_csv)


def run_case(
    root: Path,
    constructor_bin: Optional[Path],
    ns_tool: Path,
    case: Case,
    *,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
    data_size: int,
    allreduce_group_size: int,
    allreduce_placement: str,
    allreduce_step_gap: float,
    log_dir: Path,
    attempt: int,
) -> Result:
    ensure_dir(log_dir)
    safe = f"{case.name()}-try{attempt}"
    log_path = log_dir / f"{safe}.log"

    args = [
        f"--config={case.config_file}",
        f"--routing={case.routing}",
        f"--trafficPattern={traffic_pattern}",
        "--memory=true",
    ]
    if traffic_pattern in ("allreduce", "grouped-allreduce", "alltoall"):
        degree = 8 if traffic_pattern == "alltoall" else 4
        args += [
            f"--dataSize={data_size}",
            f"--degree={degree}",
        ]
    if traffic_pattern == "grouped-allreduce":
        args += [
            f"--allreduceGroupSize={allreduce_group_size}",
            f"--allreducePlacement={allreduce_placement}",
            f"--allreduceStepGap={allreduce_step_gap}",
        ]
    if traffic_pattern == "flows":
        args += [
            f"--numFlows={num_flows}",
            f"--flowSize={flow_size}",
        ]
    if constructor_bin is not None:
        cmd = [str(constructor_bin)] + args
    else:
        cmd = [str(ns_tool), "run", "constructor " + " ".join(args)]

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

    m = parse_metrics(out)
    routing = m.get("routing") or case.routing
    return Result(
        case_key=case.key(),
        name=case.name(),
        group=case.group,
        variant=case.variant,
        param_name=case.param_name,
        param_value=case.param_value,
        config=case.config_file,
        routing=routing,
        rc=proc.returncode,
        init_s=m.get("init_s"),
        exec_s=m.get("exec_s"),
        wall_s=wall,
        exec_peak_mem_kb=m.get("exec_mem_kb"),
        forward_lookup_count=m.get("forward_lookup_count"),
        forward_lookup_total_s=m.get("forward_lookup_total_s"),
        forward_lookup_avg_s=m.get("forward_lookup_avg_s"),
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Datacenter non-minimal sweep: time + memory")
    p.add_argument("--build-profile", default="optimized", choices=["debug", "optimized", "release"])
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--out", default="plots/nonminimal-time-mem.csv")
    p.add_argument("--log-dir", default="results/nonminimal-logs")
    p.add_argument("--resume-policy", default="skip_success", choices=["skip_success", "skip_any", "rerun_failed"])
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--retry-sleep", type=float, default=0.2)

    p.add_argument("--bandwidth", default="100Gbps")
    p.add_argument("--delay", default="1us")
    p.add_argument("--trafficPattern", default="grouped-allreduce", choices=["flows", "allreduce", "grouped-allreduce", "alltoall"])
    p.add_argument("--numFlows", type=int, default=10)
    p.add_argument("--flowSize", type=int, default=1048576)  # 1MB
    p.add_argument("--dataSize", type=int, default=1048576)  # 1MB
    p.add_argument("--allreduceGroupSize", type=int, default=8)
    p.add_argument("--allreducePlacement", default="strided", choices=["contiguous", "strided"])
    p.add_argument("--allreduceStepGap", type=float, default=0.0)

    p.add_argument("--only", default=None,
                   help="只跑指定组（逗号分隔）：dragonfly_valiant,dragonfly_ugal,torus_detour1,torus_detour2")
    p.add_argument("--only-h", default=None, help="只跑指定 dragonfly h（逗号分隔）")
    p.add_argument("--only-d", default=None, help="只跑指定 torus d（逗号分隔）")
    p.add_argument(
        "--torus-baseline-routing",
        default="NodeBfsWithHost",
        choices=["RuleBased", "NodeBfs", "NodeBfsStrict", "NodeBfsWithHost"],
        help=(
            "Routing used for Torus shortest baseline. 3D Torus nodes are both hosts "
            "and transit nodes, so NodeBfsWithHost is the paper BFS baseline."
        ),
    )
    args = p.parse_args()

    root = repo_root()
    ns_tool = pick_ns3_tool(root)

    if not args.skip_build:
        ns_configure_and_build(ns_tool, args.build_profile, enable_examples=True)

    constructor_bin = pick_constructor_binary(root, args.build_profile)
    if constructor_bin is not None:
        print(f"[BIN ] Using constructor binary: {constructor_bin}")
    else:
        print("[BIN ] constructor binary not found; falling back to './ns3 run constructor ...'")

    only_groups: Optional[Set[str]] = None
    if args.only:
        only_groups = {s.strip() for s in args.only.split(",") if s.strip()}

    hs = [2, 4, 6, 8, 10]
    ds = [5, 10, 15, 20]
    if args.only_h:
        hs = [int(x.strip()) for x in args.only_h.split(",") if x.strip()]
    if args.only_d:
        ds = [int(x.strip()) for x in args.only_d.split(",") if x.strip()]

    cases: List[Case] = []

    # Dragonfly Valiant / UGAL
    if only_groups is None or "dragonfly_valiant" in only_groups or "dragonfly_ugal" in only_groups:
        for h in hs:
            if only_groups is None or "dragonfly_valiant" in only_groups:
                cfg = generate_dragonfly_json(
                    root,
                    h=h,
                    algorithm="Valiant",
                    bandwidth=args.bandwidth,
                    delay=args.delay,
                    metric="bytes",
                    transit_fields="2",
                )
                cases.append(
                    Case(
                        group="dragonfly_valiant",
                        param_name="h",
                        param_value=h,
                        config_file=cfg,
                        variant="nonminimal",
                    )
                )
                base_cfg = ensure_baseline_config(root, cfg)
                cases.append(
                    Case(
                        group="dragonfly_valiant",
                        param_name="h",
                        param_value=h,
                        config_file=base_cfg,
                        variant="baseline",
                    )
                )
            if only_groups is None or "dragonfly_ugal" in only_groups:
                cfg = generate_dragonfly_json(
                    root,
                    h=h,
                    algorithm="UGAL",
                    bandwidth=args.bandwidth,
                    delay=args.delay,
                    metric="bytes",
                    transit_fields="2",
                    alpha=1.0,
                    detour_penalty=1.0,
                )
                cases.append(
                    Case(
                        group="dragonfly_ugal",
                        param_name="h",
                        param_value=h,
                        config_file=cfg,
                        variant="nonminimal",
                    )
                )
                base_cfg = ensure_baseline_config(root, cfg)
                cases.append(
                    Case(
                        group="dragonfly_ugal",
                        param_name="h",
                        param_value=h,
                        config_file=base_cfg,
                        variant="baseline",
                    )
                )

    # Torus Detour stages 1/2
    if only_groups is None or "torus_detour1" in only_groups or "torus_detour2" in only_groups:
        for d in ds:
            if only_groups is None or "torus_detour1" in only_groups:
                cfg = generate_torus_detour_json(
                    root,
                    d=d,
                    detour_stages=1,
                    bandwidth=args.bandwidth,
                    delay=args.delay,
                    metric="bytes",
                    transit_fields="0,1,2",
                )
                cases.append(
                    Case(
                        group="torus_detour1",
                        param_name="d",
                        param_value=d,
                        config_file=cfg,
                        variant="nonminimal",
                    )
                )
                base_cfg = ensure_baseline_config(root, cfg)
                cases.append(
                    Case(
                        group="torus_detour1",
                        param_name="d",
                        param_value=d,
                        config_file=base_cfg,
                        routing=args.torus_baseline_routing,
                        variant="baseline",
                    )
                )
            if only_groups is None or "torus_detour2" in only_groups:
                cfg = generate_torus_detour_json(
                    root,
                    d=d,
                    detour_stages=2,
                    bandwidth=args.bandwidth,
                    delay=args.delay,
                    metric="bytes",
                    transit_fields="0,1,2",
                )
                cases.append(
                    Case(
                        group="torus_detour2",
                        param_name="d",
                        param_value=d,
                        config_file=cfg,
                        variant="nonminimal",
                    )
                )
                base_cfg = ensure_baseline_config(root, cfg)
                cases.append(
                    Case(
                        group="torus_detour2",
                        param_name="d",
                        param_value=d,
                        config_file=base_cfg,
                        routing=args.torus_baseline_routing,
                        variant="baseline",
                    )
                )

    out_csv = root / args.out
    expected_routing_by_key = {case.key(): case.routing for case in cases}
    done = load_completed(out_csv, args.resume_policy, expected_routing_by_key)
    if done:
        print(f"[RESUME] 已从 {out_csv} 识别到 {len(done)} 个 routing 匹配的已完成 case，将自动跳过。")

    log_dir = root / args.log_dir
    ran: List[Result] = []
    total = len(cases)
    for i, c in enumerate(cases, 1):
        if c.key() in done:
            print(f"[SKIP] ({i}/{total}) {c.key()} (已完成)")
            continue
        print(f"[RUN ] ({i}/{total}) {c.key()} config={c.config_file}")

        last: Optional[Result] = None
        max_retries = max(1, int(args.max_retries))
        for attempt in range(1, max_retries + 1):
            r = run_case(
                root=root,
                constructor_bin=constructor_bin,
                ns_tool=ns_tool,
                case=c,
                traffic_pattern=args.trafficPattern,
                num_flows=args.numFlows,
                flow_size=args.flowSize,
                data_size=args.dataSize,
                allreduce_group_size=args.allreduceGroupSize,
                allreduce_placement=args.allreducePlacement,
                allreduce_step_gap=args.allreduceStepGap,
                log_dir=log_dir,
                attempt=attempt,
            )
            last = r
            if r.rc == 0:
                break
            if attempt < max_retries:
                print(f"[RETRY] {c.key()} attempt={attempt}/{max_retries} rc={r.rc} -> retrying...")
                time.sleep(float(args.retry_sleep))

        assert last is not None
        ran.append(last)
        append_one(out_csv, last)
        if args.resume_policy != "skip_any" and last.rc == 0:
            done.add(c.key())
        print(
            f"[DONE] {c.key()} rc={last.rc} wall={last.wall_s:.2f}s"
            + (f" mem={last.exec_peak_mem_gb:.3f}GB" if last.exec_peak_mem_gb is not None else "")
        )

    compact_csv_inplace(out_csv)
    print(f"[OUT ] {out_csv}")

    if ran:
        print("\n=== Summary (wall_s / exec_peak_mem_gb) ===")
        for r in ran:
            mem = "-" if r.exec_peak_mem_gb is None else f"{r.exec_peak_mem_gb:.3f}GB"
            print(f"{r.case_key}\twall={r.wall_s:.2f}s\tmem={mem}\trc={r.rc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
