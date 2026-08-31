#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Correctness verification for src/datacenter:

1) Failure correctness:
   Baseline: NodeBfsStrict
   Compare packet trace consistency under the SAME failure events for
     fattree k = 8,16,24,32
     failureRate = 0.001, 0.01, 0.1

2) Non-minimal correctness:
   Baselines:
     - DragonflyValiantRouting (dragonfly example, routing=valiant)
     - DragonflyUgalRouting    (dragonfly example, routing=ugal)
     - TorusDetourRouting      (torus_detour example)
   Compare packet traces vs RuleBased non-minimal policy in constructor for:
     - dragonfly h = 2,4,6 (full-size: a=2h, p=h, g=a*h+1)
     - torus d = 5,10,15 (3D: nodes = d^3), stages=1 and 2

Notes:
- This script runs programs and diffs packet traces in src/datacenter/examples/traces/.
- It ignores comment lines starting with '#'.
- It retries a case a few times if it exits non-zero (to handle occasional flakiness).
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def run(cmd: List[str], cwd: Path, env: Dict[str, str], log_path: Path) -> int:
    ensure_dir(log_path.parent)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n\n")
        f.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            f.write(line)
        return proc.wait()


def pick_binary(root: Path, rel: str) -> Optional[Path]:
    p = root / rel
    return p if p.exists() and os.access(p, os.X_OK) else None


def pick_ns3_tool(root: Path) -> Path:
    for name in ("ns3", "ns", "waf"):
        p = root / name
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise SystemExit("未找到构建工具：期望 repo 根目录存在可执行的 ./ns3 或 ./ns 或 ./waf")


def strip_trace_lines(path: Path) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line:
                continue
            if line.lstrip().startswith("#"):
                continue
            out.append(line)
    return out


def diff_files(a: Path, b: Path, diff_out: Path) -> bool:
    la = strip_trace_lines(a)
    lb = strip_trace_lines(b)
    if la == lb:
        return True
    ensure_dir(diff_out.parent)
    with open(diff_out, "w", encoding="utf-8") as f:
        for ln in difflib.unified_diff(la, lb, fromfile=str(a), tofile=str(b), lineterm=""):
            f.write(ln + "\n")
    return False


def find_traces_dir(root: Path) -> Path:
    return root / "src/datacenter/examples/traces"


def constructor_packet_trace_path(traces_dir: Path, config: str, algo: str, failure: str) -> Path:
    config_stem = Path(config).stem
    failure_suffix = f"_{Path(failure).stem}" if failure else ""
    return traces_dir / f"{config_stem}_{algo}{failure_suffix}_packet_trace.txt"


def dragonfly_packet_trace_path(traces_dir: Path, trace_prefix: str) -> Path:
    return traces_dir / f"{trace_prefix}_packet_trace.txt"


def torus_detour_packet_trace_path(traces_dir: Path, trace_prefix: str) -> Path:
    return traces_dir / f"{trace_prefix}_packet_trace.txt"


def copy_trace_cmd(src: Path, dst: Path) -> List[str]:
    return [
        sys.executable,
        "-c",
        (
            "import pathlib,shutil,sys;"
            "pathlib.Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True);"
            "shutil.copy2(sys.argv[1], sys.argv[2])"
        ),
        str(src),
        str(dst),
    ]


def traffic_args(traffic_pattern: str, *, num_flows: Optional[int], flow_size: Optional[int]) -> List[str]:
    args = [f"--trafficPattern={traffic_pattern}"]
    if flow_size is not None:
        args.append(f"--flowSize={flow_size}")
        if traffic_pattern in {"allreduce", "alltoall"}:
            args.append(f"--dataSize={flow_size}")
    if traffic_pattern == "flows" and num_flows is not None:
        args.append(f"--numFlows={num_flows}")
    return args


def gen_fattree_config_name(k: int, bandwidth: str, delay: str) -> str:
    bw_clean = bandwidth.replace("Gbps", "g").replace("Mbps", "m").replace("bps", "b")
    delay_clean = delay.replace("us", "u").replace("ns", "n").replace("ms", "m")
    return f"fattree_k{k}_{bw_clean}_{delay_clean}.json"


def ensure_fattree_config(root: Path, k: int, bandwidth: str, delay: str) -> str:
    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    cmd = [sys.executable, str(gen), "fattree", "--k", str(k), "--bandwidth", bandwidth, "--delay", delay]
    log = root / "results/correctness" / f"gen-ft-k{k}.log"
    rc = run(cmd, root, base_env(), log)
    if rc != 0:
        raise SystemExit(f"生成 fattree JSON 失败（k={k}），详见 {log}")
    return gen_fattree_config_name(k, bandwidth, delay)


def ensure_dragonfly_config(
    root: Path,
    h: int,
    alg: str,
    bandwidth: str,
    delay: str,
    seed: int,
) -> str:
    # full-size: a=2h, p=h, g=a*h+1, strategy Absolute
    a = 2 * h
    p = h
    g = a * h + 1
    alg_tag = alg.lower()
    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    output_name = f"dragonfly_{alg_tag}.json"
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
        "--output",
        output_name,
        "--bandwidth",
        bandwidth,
        "--delay",
        delay,
        "--nonminimal",
        "--nonminimal-algorithm",
        alg,
        "--nonminimal-metric",
        "bytes",
        "--nonminimal-transit-fields",
        "2",
        "--nonminimal-seed",
        str(seed),
    ]
    if alg.lower() == "ugal":
        cmd += ["--nonminimal-alpha", "1.0", "--nonminimal-detour-penalty", "1.0"]
    log = root / "results/correctness" / f"gen-df-{alg}-h{h}.log"
    rc = run(cmd, root, base_env(), log)
    if rc != 0:
        raise SystemExit(f"生成 dragonfly JSON 失败（h={h}, alg={alg}），详见 {log}")
    # generator will place file under inputs/, but we can infer suffix
    bw_clean = bandwidth.replace("Gbps", "g").replace("Mbps", "m").replace("bps", "b")
    delay_clean = delay.replace("us", "u").replace("ns", "n").replace("ms", "m")
    return f"dragonfly_{alg_tag}_g{g}_a{a}_p{p}_h{h}_{bw_clean}_{delay_clean}.json"


def ensure_torus_config(root: Path, d: int, stages: int, bandwidth: str, delay: str) -> str:
    gen = root / "src/datacenter/examples/inputs/topology_generator.py"
    out_name = f"torus3d_d{d}_detour{stages}.json"
    # same custom levels encoding as nonminimal_sweep.py (3D torus)
    levels = (
        f'[{{"dims":['
        f'{{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":{d},"LinkArrangement":"SameRank"}},'
        f'{{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":{d},"LinkArrangement":"SameRank"}},'
        f'{{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":{d},"LinkArrangement":"SameRank"}}'
        f']}}]'
    )
    cmd = [
        sys.executable,
        str(gen),
        "custom",
        "-o",
        out_name,
        "--levels",
        levels,
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
        "bytes",
        "--nonminimal-transit-fields",
        "0,1,2",
        "--nonminimal-detour-stages",
        str(stages),
    ]
    log = root / "results/correctness" / f"gen-torus-d{d}-s{stages}.log"
    rc = run(cmd, root, base_env(), log)
    if rc != 0:
        raise SystemExit(f"生成 torus JSON 失败（d={d}, stages={stages}），详见 {log}")
    return out_name


def base_env() -> Dict[str, str]:
    env = dict(os.environ)
    # Keep traces quieter / deterministic by default.
    env.setdefault("NVWA_WITHDRAW_TRACE", "0")
    return env


@dataclass(frozen=True)
class Case:
    name: str
    run_cmds: List[Tuple[str, List[str]]]  # label -> cmd
    trace_pairs: List[Tuple[str, Path, Path, Path]]  # label, left, right, diff_out


def run_with_retries(root: Path, case: Case, retries: int, sleep_s: float) -> Tuple[bool, List[str]]:
    """
    Run all commands in the case (in order). Return (ok, errors).
    """
    errors: List[str] = []
    env = base_env()
    for label, cmd in case.run_cmds:
        last_rc = None
        for attempt in range(1, retries + 1):
            log_path = root / "results/correctness" / "logs" / f"{case.name}__{label}__try{attempt}.log"
            rc = run(cmd, root, env, log_path)
            last_rc = rc
            if rc == 0:
                break
            if attempt < retries:
                time.sleep(sleep_s)
        if last_rc != 0:
            errors.append(f"{case.name}: command '{label}' failed (rc={last_rc})")
            return False, errors

    for label, left, right, diff_out in case.trace_pairs:
        if not left.exists():
            errors.append(f"{case.name}: missing left trace for {label}: {left}")
            return False, errors
        if not right.exists():
            errors.append(f"{case.name}: missing right trace for {label}: {right}")
            return False, errors
        ok = diff_files(left, right, diff_out)
        if not ok:
            errors.append(f"{case.name}: trace mismatch for {label}. diff: {diff_out}")
            return False, errors

    return True, errors


def build_failure_cases(
    root: Path,
    *,
    ks: Sequence[int],
    rates: Sequence[float],
    bandwidth: str,
    delay: str,
    seed: int,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
) -> List[Case]:
    traces = find_traces_dir(root)
    ensure_dir(traces)
    constructor = pick_binary(root, "build/src/datacenter/examples/ns3-dev-constructor-optimized")
    if constructor is None:
        raise SystemExit("找不到 constructor 二进制：build/src/datacenter/examples/ns3-dev-constructor-optimized")

    cases: List[Case] = []
    for k in ks:
        config = ensure_fattree_config(root, k, bandwidth, delay)
        for fr in rates:
            fr_tag = f"{fr:g}".replace(".", "p")
            failure_json = f"auto_ft_k{k}_fr{fr_tag}_seed{seed}.json"
            # Step 1: generate deterministic failure json (fast; no debug)
            gen_cmd = [
                str(constructor),
                f"--config={config}",
                "--routing=RuleBased",
                f"--randomFailureRate={fr}",
                "--randomFailureTime=0.5",
                "--randomFailureTimeUnit=s",
                f"--randomFailureSeed={seed}",
                f"--randomFailureOut={failure_json}",
            ]
            gen_cmd += traffic_args(traffic_pattern, num_flows=0, flow_size=1)

            # Step 2/3: run debug traces for both routings using same failure json
            rb_cmd = [
                str(constructor),
                f"--config={config}",
                "--routing=RuleBased",
                "--debug=1",
                f"--failure={failure_json}",
            ]
            rb_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)
            bfs_cmd = [
                str(constructor),
                f"--config={config}",
                "--routing=NodeBfsStrict",
                "--debug=1",
                f"--failure={failure_json}",
            ]
            bfs_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)

            left = constructor_packet_trace_path(traces, config, "NodeBfsStrict", failure_json)
            right = constructor_packet_trace_path(traces, config, "RuleBased", failure_json)
            diff_out = root / "results/correctness" / "diffs" / f"failure_ftk{k}_fr{fr_tag}.diff"

            cases.append(
                Case(
                    name=f"failure_ftk{k}_fr{fr_tag}",
                    run_cmds=[
                        ("gen_fail_json", gen_cmd),
                        ("nodebfsstrict", bfs_cmd),
                        ("rulebased", rb_cmd),
                    ],
                    trace_pairs=[("NodeBfsStrict_vs_RuleBased", left, right, diff_out)],
                )
            )
    return cases


def build_nonminimal_cases(
    root: Path,
    *,
    hs: Sequence[int],
    ds: Sequence[int],
    torus_stages: Sequence[int],
    bandwidth: str,
    delay: str,
    traffic_pattern: str,
    num_flows: int,
    flow_size: int,
    dragonfly_seed: int,
    dragonfly_algs: Sequence[str],
    include_torus: bool,
) -> List[Case]:
    traces = find_traces_dir(root)
    ensure_dir(traces)

    constructor = pick_binary(root, "build/src/datacenter/examples/ns3-dev-constructor-optimized")
    if constructor is None:
        raise SystemExit("缺少二进制：constructor（请先 ./ns3 build）")

    do_dragonfly = len(dragonfly_algs) > 0
    do_torus = include_torus

    dragonfly = None
    if do_dragonfly:
        dragonfly = pick_binary(root, "build/src/datacenter/examples/ns3-dev-dragonfly-optimized")
        if dragonfly is None:
            raise SystemExit("缺少二进制：dragonfly（请先 ./ns3 build）")

    torus_detour = None
    if do_torus:
        torus_detour = pick_binary(root, "build/src/datacenter/examples/ns3-dev-torus_detour-optimized")
        if torus_detour is None:
            raise SystemExit("缺少二进制：torus_detour（请先 ./ns3 build）")

    cases: List[Case] = []

    # Dragonfly Valiant / UGAL
    if do_dragonfly:
        alg_map = {
            "valiant": ("Valiant", "valiant", "dvr"),
            "ugal": ("UGAL", "ugal", "dur"),
        }
        for h in hs:
            a = 2 * h
            p = h
            g = a * h + 1

            for alg_key in dragonfly_algs:
                key = alg_key.lower()
                if key not in alg_map:
                    raise SystemExit(f"未知 dragonfly 算法：{alg_key}（支持: valiant, ugal）")
                alg, routing_arg, prefix_tag = alg_map[key]
                config = ensure_dragonfly_config(root, h, alg, bandwidth, delay, dragonfly_seed)
                trace_prefix = f"baseline_dragonfly_{prefix_tag}_h{h}"
                rulebased_tag = f"RuleBased_{routing_arg}"

                rb_cmd = [
                    str(constructor),
                    f"--config={config}",
                    "--routing=RuleBased",
                    "--debug=1",
                ]
                rb_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)
                rb_src = constructor_packet_trace_path(traces, config, "RuleBased", "")
                rb_dst = constructor_packet_trace_path(traces, config, rulebased_tag, "")
                rb_copy_cmd = copy_trace_cmd(rb_src, rb_dst)
                base_cmd = [
                    str(dragonfly),
                    f"--groups={g}",
                    f"--routersPerGroup={a}",
                    f"--hostsPerRouter={p}",
                    f"--globalLinksPerRouter={h}",
                    f"--seed={dragonfly_seed}",
                    f"--routing={routing_arg}",
                    f"--rate={bandwidth}",
                    f"--delay={delay}",
                    "--debug=1",
                    f"--tracePrefix={trace_prefix}",
                ]
                base_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)

                # Compare baseline trace vs constructor trace (RuleBased)
                left = dragonfly_packet_trace_path(traces, trace_prefix)
                right = rb_dst
                diff_out = root / "results/correctness" / "diffs" / f"nonminimal_dragonfly_{prefix_tag}_h{h}.diff"

                cases.append(
                    Case(
                        name=f"nonminimal_dragonfly_{prefix_tag}_h{h}",
                        run_cmds=[
                            ("rulebased_constructor", rb_cmd),
                            ("tag_rulebased_trace", rb_copy_cmd),
                            ("baseline_dragonfly", base_cmd),
                        ],
                        trace_pairs=[("baseline_vs_rulebased", left, right, diff_out)],
                    )
                )

    # Torus Detour stages
    if do_torus:
        for d in ds:
            for st in torus_stages:
                config = ensure_torus_config(root, d, st, bandwidth, delay)
                trace_prefix = f"baseline_torus_detour_d{d}_s{st}"

                rb_cmd = [
                    str(constructor),
                    f"--config={config}",
                    "--routing=RuleBased",
                    "--debug=1",
                ]
                rb_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)
                base_cmd = [
                    str(torus_detour),
                    f"--d={d}",
                    f"--detourStages={st}",
                    "--transitFields=0,1,2",
                    f"--rate={bandwidth}",
                    f"--delay={delay}",
                    "--debug=1",
                    f"--tracePrefix={trace_prefix}",
                ]
                base_cmd += traffic_args(traffic_pattern, num_flows=num_flows, flow_size=flow_size)

                left = torus_detour_packet_trace_path(traces, trace_prefix)
                right = constructor_packet_trace_path(traces, config, "RuleBased", "")
                diff_out = root / "results/correctness" / "diffs" / f"nonminimal_torus_d{d}_s{st}.diff"

                cases.append(
                    Case(
                        name=f"nonminimal_torus_d{d}_s{st}",
                        run_cmds=[
                            ("rulebased_constructor", rb_cmd),
                            ("baseline_torus_detour", base_cmd),
                        ],
                        trace_pairs=[("baseline_vs_rulebased", left, right, diff_out)],
                    )
                )

    return cases


def add_common_traffic_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--trafficPattern", default="allreduce", choices=["flows", "allreduce"])
    p.add_argument("--numFlows", type=int, default=10)
    p.add_argument("--flowSize", type=int, default=1048576)


def add_common_link_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--bandwidth", default="100Gbps")
    p.add_argument("--delay", default="1us")


def add_retry_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--retries", type=int, default=8)
    p.add_argument("--retry-sleep", type=float, default=0.2)


def main() -> int:
    p = argparse.ArgumentParser(description="Datacenter correctness checks (failure + non-minimal)")
    sub = p.add_subparsers(dest="mode", required=True)

    pf = sub.add_parser("failure", help="Compare failure packet traces: NodeBfsStrict vs RuleBased")
    pf.add_argument("--k", default="8,16,24,32")
    pf.add_argument("--rates", default="0.001,0.01,0.1")
    pf.add_argument("--seed", type=int, default=1)
    add_common_link_flags(pf)
    add_common_traffic_flags(pf)
    add_retry_flags(pf)

    pn = sub.add_parser("nonminimal", help="Compare non-minimal packet traces vs baselines (dragonfly + torus)")
    pn.add_argument("--h", default="2,4,6")
    pn.add_argument("--d", default="5,10,15")
    pn.add_argument("--torus-stages", default="1,2")
    pn.add_argument("--dragonfly-seed", type=int, default=1)
    add_common_link_flags(pn)
    add_common_traffic_flags(pn)
    add_retry_flags(pn)

    pn_dv = sub.add_parser("nonminimal-dragonfly-valiant", help="Dragonfly Valiant correctness (RuleBased vs dvr)")
    pn_dv.add_argument("--h", default="2,4,6")
    pn_dv.add_argument("--dragonfly-seed", type=int, default=1)
    add_common_link_flags(pn_dv)
    add_common_traffic_flags(pn_dv)
    add_retry_flags(pn_dv)

    pn_du = sub.add_parser("nonminimal-dragonfly-ugal", help="Dragonfly UGAL correctness (RuleBased vs dur)")
    pn_du.add_argument("--h", default="2,4,6")
    pn_du.add_argument("--dragonfly-seed", type=int, default=1)
    add_common_link_flags(pn_du)
    add_common_traffic_flags(pn_du)
    add_retry_flags(pn_du)

    pn_td = sub.add_parser("nonminimal-torus-detour", help="Torus Detour correctness (RuleBased vs detour)")
    pn_td.add_argument("--d", default="5,10,15")
    pn_td.add_argument("--torus-stages", default="1,2")
    add_common_link_flags(pn_td)
    add_common_traffic_flags(pn_td)
    add_retry_flags(pn_td)

    args = p.parse_args()
    root = repo_root()
    ensure_dir(root / "results/correctness/logs")
    ensure_dir(root / "results/correctness/diffs")

    if args.mode == "failure":
        ks = [int(x.strip()) for x in args.k.split(",") if x.strip()]
        rates = [float(x.strip()) for x in args.rates.split(",") if x.strip()]
        cases = build_failure_cases(
            root,
            ks=ks,
            rates=rates,
            bandwidth=args.bandwidth,
            delay=args.delay,
            seed=args.seed,
            traffic_pattern=args.trafficPattern,
            num_flows=args.numFlows,
            flow_size=args.flowSize,
        )
    elif args.mode == "nonminimal":
        hs = [int(x.strip()) for x in args.h.split(",") if x.strip()]
        ds = [int(x.strip()) for x in args.d.split(",") if x.strip()]
        stages = [int(x.strip()) for x in args.torus_stages.split(",") if x.strip()]
        cases = build_nonminimal_cases(
            root,
            hs=hs,
            ds=ds,
            torus_stages=stages,
            bandwidth=args.bandwidth,
            delay=args.delay,
            traffic_pattern=args.trafficPattern,
            num_flows=args.numFlows,
            flow_size=args.flowSize,
            dragonfly_seed=int(args.dragonfly_seed),
            dragonfly_algs=["valiant", "ugal"],
            include_torus=True,
        )
    elif args.mode == "nonminimal-dragonfly-valiant":
        hs = [int(x.strip()) for x in args.h.split(",") if x.strip()]
        cases = build_nonminimal_cases(
            root,
            hs=hs,
            ds=[],
            torus_stages=[],
            bandwidth=args.bandwidth,
            delay=args.delay,
            traffic_pattern=args.trafficPattern,
            num_flows=args.numFlows,
            flow_size=args.flowSize,
            dragonfly_seed=int(args.dragonfly_seed),
            dragonfly_algs=["valiant"],
            include_torus=False,
        )
    elif args.mode == "nonminimal-dragonfly-ugal":
        hs = [int(x.strip()) for x in args.h.split(",") if x.strip()]
        cases = build_nonminimal_cases(
            root,
            hs=hs,
            ds=[],
            torus_stages=[],
            bandwidth=args.bandwidth,
            delay=args.delay,
            traffic_pattern=args.trafficPattern,
            num_flows=args.numFlows,
            flow_size=args.flowSize,
            dragonfly_seed=int(args.dragonfly_seed),
            dragonfly_algs=["ugal"],
            include_torus=False,
        )
    elif args.mode == "nonminimal-torus-detour":
        ds = [int(x.strip()) for x in args.d.split(",") if x.strip()]
        stages = [int(x.strip()) for x in args.torus_stages.split(",") if x.strip()]
        cases = build_nonminimal_cases(
            root,
            hs=[],
            ds=ds,
            torus_stages=stages,
            bandwidth=args.bandwidth,
            delay=args.delay,
            traffic_pattern=args.trafficPattern,
            num_flows=args.numFlows,
            flow_size=args.flowSize,
            dragonfly_seed=1,
            dragonfly_algs=[],
            include_torus=True,
        )
    else:
        raise SystemExit(f"未知模式：{args.mode}")

    total = len(cases)
    ok_count = 0
    failed: List[str] = []

    for i, c in enumerate(cases, 1):
        print(f"[RUN ] ({i}/{total}) {c.name}")
        ok, errs = run_with_retries(root, c, retries=int(args.retries), sleep_s=float(args.retry_sleep))
        if ok:
            ok_count += 1
            print(f"[OK  ] {c.name}")
        else:
            failed.extend(errs)
            print(f"[FAIL] {c.name}")
            for e in errs:
                print("  - " + e)

    print(f"\n[SUMMARY] ok={ok_count}/{total}")
    if failed:
        print("[FAILED]")
        for e in failed:
            print("- " + e)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
