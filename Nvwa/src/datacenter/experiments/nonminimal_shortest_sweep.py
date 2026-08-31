#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shortest-path baselines for non-minimal experiments (Dragonfly / Torus).

目标：
- Dragonfly shortest: h = 2,4,6,8,10
- 3D Torus shortest: d = 5,10,15,20
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
    log = root / "results" / f"build-nonminimal-shortest-{int(time.time())}.log"
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


def generate_dragonfly_json(root: Path, *, h: int, bandwidth: str, delay: str) -> str:
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
    ]
    log = root / "results" / f"gen-dragonfly-shortest-h{h}-{int(time.time())}.log"
    rc, out = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Dragonfly JSON 失败（h={h}, rc={rc}），详见：{log}")

    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if not m:
        raise SystemExit(f"无法从 generator 输出解析文件名（h={h}）。详见：{log}")
    return m.group(1).strip()


def _torus_3d_levels_json(d: int) -> str:
    # 3D torus: three TorusIntraLevel dimensions, each subBlockNum = d.
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


def generate_torus_json(root: Path, *, d: int, bandwidth: str, delay: str) -> str:
    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    if not gen.exists():
        raise SystemExit(f"未找到 generator：{gen}")

    out_name = f"torus3d_d{d}_shortest.json"
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
    ]
    log = root / "results" / f"gen-torus3d-shortest-d{d}-{int(time.time())}.log"
    rc, out = run_logged(cmd, root, log)
    if rc != 0:
        raise SystemExit(f"生成 Torus JSON 失败（d={d}, rc={rc}），详见：{log}")

    m = re.search(r"^Output file:\s*(\S+)\s*$", out, re.M)
    if not m:
        return out_name
    return m.group(1).strip()


@dataclass(frozen=True)
class Case:
    group: str          # "dragonfly_shortest" | "torus_shortest"
    param_name: str     # "h" or "d"
    param_value: int
    config_file: str

    def key(self) -> str:
        return f"{self.group}:{self.param_name}={self.param_value}"


@dataclass(frozen=True)
class Result:
    case_key: str
    group: str
    param_name: str
    param_value: int
    config: str
    routing: str
    rc: int
    init_s: Optional[float]
    exec_s: Optional[float]
    wall_s: float
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
    return {
        "init_s": init_s,
        "exec_s": exec_s,
        "routing": routing,
        "init_mem_kb": init_mem_kb,
        "exec_mem_kb": exec_mem_kb,
    }


def topology_tag_for_shortest(only_groups: Optional[Set[str]]) -> str:
    has_dragonfly = "dragonfly_shortest" in (only_groups or set())
    has_torus = "torus_shortest" in (only_groups or set())
    if has_dragonfly:
        return "Dragonfly"
    if has_torus:
        return "Torus"
    return "Dragonfly"


def run_case(
    root: Path,
    constructor_bin: Optional[Path],
    ns_tool: Path,
    case: Case,
    *,
    routing: str,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
    log_dir: Path,
    attempt: int,
) -> Result:
    ensure_dir(log_dir)
    safe = f"{case.group}-{case.param_name}{case.param_value}-try{attempt}"
    log_path = log_dir / f"{safe}.log"

    args = [
        f"--config={case.config_file}",
        f"--routing={routing}",
        f"--trafficPattern={traffic_pattern}",
        f"--flowSize={flow_size}",
        "--memory=true",
    ]
    if traffic_pattern == "flows":
        args.append(f"--numFlows={num_flows}")
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
    routing_used = m.get("routing") or routing
    return Result(
        case_key=case.key(),
        group=case.group,
        param_name=case.param_name,
        param_value=case.param_value,
        config=case.config_file,
        routing=routing_used,
        rc=proc.returncode,
        init_s=m.get("init_s"),
        exec_s=m.get("exec_s"),
        wall_s=wall,
        exec_peak_mem_kb=m.get("exec_mem_kb"),
    )


def ensure_csv_header(out_csv: Path) -> None:
    ensure_dir(out_csv.parent)
    if out_csv.exists() and out_csv.stat().st_size > 0:
        return
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "case_key",
                "group",
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
            ]
        )


def append_one(out_csv: Path, r: Result) -> None:
    ensure_csv_header(out_csv)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                r.case_key,
                r.group,
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


def load_completed(out_csv: Path, resume_policy: str) -> Set[str]:
    completed: Set[str] = set()
    for r in _csv_read_rows(out_csv):
        key = (r.get("case_key") or "").strip()
        if not key:
            continue
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


def main() -> int:
    p = argparse.ArgumentParser(description="Non-minimal shortest baselines (Dragonfly/Torus)")
    p.add_argument("--build-profile", default="optimized", choices=["debug", "optimized", "release"])
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--routing", default="NodeBfs", choices=["RuleBased", "NodeBfs", "Global", "NodeBfsStrict", "NodeBfsWithHost"])
    p.add_argument("--out", default="plots/nonminimal-shortest-time-mem.csv")
    p.add_argument("--log-dir", default="results/nonminimal-shortest-logs")
    p.add_argument("--resume-policy", default="skip_success", choices=["skip_success", "skip_any", "rerun_failed"])
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--retry-sleep", type=float, default=0.2)

    p.add_argument("--bandwidth", default="100Gbps")
    p.add_argument("--delay", default="1us")
    p.add_argument("--trafficPattern", default="allreduce", choices=["flows", "allreduce", "alltoall"])
    p.add_argument("--numFlows", type=int, default=10)
    p.add_argument("--flowSize", type=int, default=1048576)

    p.add_argument("--only", default=None,
                   help="只跑指定组（逗号分隔）：dragonfly_shortest,torus_shortest")
    p.add_argument("--only-h", default=None, help="只跑指定 dragonfly h（逗号分隔）")
    p.add_argument("--only-d", default=None, help="只跑指定 torus d（逗号分隔）")
    args = p.parse_args()

    only_groups: Optional[Set[str]] = None
    if args.only:
        only_groups = {s.strip() for s in args.only.split(",") if s.strip()}
    if not only_groups:
        raise SystemExit("请用 --only 指定 dragonfly_shortest 或 torus_shortest，或使用拆分脚本分别运行。")
    has_dragonfly = "dragonfly_shortest" in only_groups
    has_torus = "torus_shortest" in only_groups
    if has_dragonfly and has_torus:
        raise SystemExit("请分开运行：--only 不能同时包含 dragonfly_shortest 和 torus_shortest。")

    default_out = "plots/nonminimal-shortest-time-mem.csv"
    default_log = "results/nonminimal-shortest-logs"
    topo_tag = topology_tag_for_shortest(only_groups)
    if args.out == default_out:
        args.out = default_out_name("shortest", topo_tag, args.routing, args.trafficPattern, args.flowSize)
    if args.log_dir == default_log:
        args.log_dir = default_log_dir("shortest", topo_tag, args.routing, args.trafficPattern, args.flowSize)

    root = repo_root()
    ns_tool = pick_ns3_tool(root)

    if not args.skip_build:
        ns_configure_and_build(ns_tool, args.build_profile, enable_examples=True)

    constructor_bin = pick_constructor_binary(root, args.build_profile)
    if constructor_bin is not None:
        print(f"[BIN ] Using constructor binary: {constructor_bin}")
    else:
        print("[BIN ] constructor binary not found; falling back to './ns3 run constructor ...'")

    out_csv = root / args.out
    done = load_completed(out_csv, args.resume_policy)

    hs = [2, 4, 6, 8, 10]
    ds = [5, 10, 15, 20]
    if args.only_h:
        hs = [int(x.strip()) for x in args.only_h.split(",") if x.strip()]
    if args.only_d:
        ds = [int(x.strip()) for x in args.only_d.split(",") if x.strip()]

    cases: List[Case] = []
    if "dragonfly_shortest" in only_groups:
        for h in hs:
            cfg = generate_dragonfly_json(root, h=h, bandwidth=args.bandwidth, delay=args.delay)
            cases.append(Case(group="dragonfly_shortest", param_name="h", param_value=h, config_file=cfg))

    if "torus_shortest" in only_groups:
        for d in ds:
            cfg = generate_torus_json(root, d=d, bandwidth=args.bandwidth, delay=args.delay)
            cases.append(Case(group="torus_shortest", param_name="d", param_value=d, config_file=cfg))

    log_dir = root / args.log_dir
    total = len(cases)
    for i, c in enumerate(cases, 1):
        if c.key() in done:
            print(f"[SKIP] ({i}/{total}) {c.key()} (已完成)")
            continue
        print(f"[RUN ] ({i}/{total}) {c.key()} config={c.config_file}")

        last: Optional[Result] = None
        for attempt in range(1, max(1, int(args.max_retries)) + 1):
            r = run_case(
                root=root,
                constructor_bin=constructor_bin,
                ns_tool=ns_tool,
                case=c,
                routing=args.routing,
                traffic_pattern=args.trafficPattern,
                num_flows=args.numFlows,
                flow_size=args.flowSize,
                log_dir=log_dir,
                attempt=attempt,
            )
            last = r
            if r.rc == 0:
                break
            if attempt < args.max_retries:
                print(f"[RETRY] {c.key()} attempt={attempt}/{args.max_retries} rc={r.rc} -> retrying...")
                time.sleep(float(args.retry_sleep))

        assert last is not None
        append_one(out_csv, last)
        if last.rc == 0:
            done.add(c.key())
        print(
            f"[DONE] {c.key()} rc={last.rc} wall={last.wall_s:.2f}s"
            + (f" mem={last.exec_peak_mem_gb:.3f}GB" if last.exec_peak_mem_gb is not None else "")
        )

    compact_csv_inplace(out_csv)
    print(f"[OUT ] {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
