#!/usr/bin/env python3
"""
Convert ATLAHS/GOAL text schedules into Nvwa constructor traffic traces.

The emitted CSV is consumed by:
  constructor --trafficPattern=trace --trafficTrace=<csv>

This is a traffic-demand bridge: every GOAL send becomes one ns-3 flow with
columns start_s,src,dst,bytes,tag. GOAL dependencies are used only to estimate
relative start times in this first-stage adapter; the ns-3 run does not yet
feed packet completion events back into the GOAL DAG.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TextIO, Tuple


RANK_RE = re.compile(r"^\s*rank\s+(\d+)\s*\{\s*$")
NUM_RANKS_RE = re.compile(r"^\s*num_ranks\s+(\d+)\s*$")
SEND_RE = re.compile(
    r"^\s*(?:(?P<label>[^:\s]+)\s*:\s*)?"
    r"send\s+(?P<size>\d+)b?\s+to\s+(?P<peer>\d+)\s+tag\s+(?P<tag>\d+)"
    r"(?:\s+cpu\s+\d+)?(?:\s+nic\s+\d+)?\s*$"
)
RECV_RE = re.compile(
    r"^\s*(?:(?P<label>[^:\s]+)\s*:\s*)?"
    r"recv\s+(?P<size>\d+)b?\s+from\s+(?P<peer>\d+)\s+tag\s+(?P<tag>\d+)"
    r"(?:\s+cpu\s+\d+)?(?:\s+nic\s+\d+)?\s*$"
)
CALC_RE = re.compile(
    r"^\s*(?:(?P<label>[^:\s]+)\s*:\s*)?"
    r"calc\s+(?P<size>\d+)(?:b)?(?:\s+cpu\s+\d+)?(?:\s+nic\s+\d+)?\s*$"
)
DEP_RE = re.compile(r"^\s*(?P<tail>[^:\s]+)\s+(?P<kind>i?requires)\s+(?P<head>\S+)\s*$")


@dataclass
class GoalOp:
    rank: int
    label: str
    kind: str
    size: int
    peer: Optional[int]
    tag: int
    order: int
    finish_deps: List[str] = field(default_factory=list)
    start_deps: List[str] = field(default_factory=list)
    start_s: float = 0.0
    finish_s: float = 0.0


def strip_comment(line: str) -> str:
    line = re.sub(r"/\*.*?\*/", "", line)
    return line.split("#", 1)[0].strip()


def make_auto_label(rank: int, order: int) -> str:
    return f"__rank{rank}_op{order}"


def parse_goal(path: Path) -> Tuple[int, Dict[int, Dict[str, GoalOp]]]:
    num_ranks: Optional[int] = None
    current_rank: Optional[int] = None
    rank_order: Dict[int, int] = {}
    ops: Dict[int, Dict[str, GoalOp]] = {}

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_no, raw in enumerate(f, start=1):
            line = strip_comment(raw)
            if not line:
                continue

            m = NUM_RANKS_RE.match(line)
            if m:
                num_ranks = int(m.group(1))
                continue

            m = RANK_RE.match(line)
            if m:
                current_rank = int(m.group(1))
                ops.setdefault(current_rank, {})
                rank_order.setdefault(current_rank, 0)
                continue

            if line == "}":
                current_rank = None
                continue

            if current_rank is None:
                continue

            dep = DEP_RE.match(line)
            if dep:
                tail = dep.group("tail")
                head = dep.group("head")
                if tail not in ops[current_rank]:
                    raise SystemExit(f"{path}:{line_no}: dependency tail {tail!r} is undefined")
                if dep.group("kind") == "irequires":
                    ops[current_rank][tail].start_deps.append(head)
                else:
                    ops[current_rank][tail].finish_deps.append(head)
                continue

            for kind, regex in (("send", SEND_RE), ("recv", RECV_RE), ("calc", CALC_RE)):
                m = regex.match(line)
                if not m:
                    continue
                order = rank_order[current_rank]
                rank_order[current_rank] = order + 1
                label = m.group("label") or make_auto_label(current_rank, order)
                peer = int(m.group("peer")) if "peer" in m.groupdict() and m.group("peer") else None
                tag = int(m.group("tag")) if "tag" in m.groupdict() and m.group("tag") else 0
                if label in ops[current_rank]:
                    raise SystemExit(f"{path}:{line_no}: duplicate label {label!r} in rank {current_rank}")
                ops[current_rank][label] = GoalOp(
                    rank=current_rank,
                    label=label,
                    kind=kind,
                    size=int(m.group("size")),
                    peer=peer,
                    tag=tag,
                    order=order,
                )
                break
            else:
                raise SystemExit(f"{path}:{line_no}: unsupported GOAL line: {raw.rstrip()}")

    if num_ranks is None:
        raise SystemExit(f"{path}: missing num_ranks header")
    return num_ranks, ops


def schedule_goal(
    ops_by_rank: Dict[int, Dict[str, GoalOp]],
    calc_scale_s_per_unit: float,
    op_duration_s: float,
    rank_sequence_gap_s: float,
) -> None:
    for rank, ops in ops_by_rank.items():
        scheduled: Dict[str, GoalOp] = {}
        pending = dict(ops)
        while pending:
            progressed = False
            for label, op in sorted(list(pending.items()), key=lambda item: item[1].order):
                deps = op.finish_deps + op.start_deps
                missing = [dep for dep in deps if dep not in ops]
                if missing:
                    raise SystemExit(
                        f"rank {rank}: operation {label} references undefined dependencies {missing}"
                    )
                if any(dep not in scheduled for dep in deps):
                    continue

                start_s = 0.0
                for dep in op.finish_deps:
                    start_s = max(start_s, scheduled[dep].finish_s)
                for dep in op.start_deps:
                    start_s = max(start_s, scheduled[dep].start_s)
                if rank_sequence_gap_s > 0:
                    start_s = max(start_s, op.order * rank_sequence_gap_s)

                duration_s = op_duration_s
                if op.kind == "calc":
                    duration_s = op.size * calc_scale_s_per_unit
                op.start_s = start_s
                op.finish_s = start_s + duration_s
                scheduled[label] = op
                del pending[label]
                progressed = True

            if not progressed:
                cycle = ", ".join(sorted(pending))
                raise SystemExit(f"rank {rank}: cannot schedule GOAL dependencies; cycle near {cycle}")


def iter_send_flows(
    ops_by_rank: Dict[int, Dict[str, GoalOp]],
    host_count: Optional[int],
    map_modulo_hosts: bool,
) -> Iterable[GoalOp]:
    for rank in sorted(ops_by_rank):
        for op in sorted(ops_by_rank[rank].values(), key=lambda item: (item.start_s, item.order)):
            if op.kind != "send":
                continue
            if op.size == 0:
                continue
            assert op.peer is not None
            if host_count is not None:
                if map_modulo_hosts:
                    op = replace(op, rank=op.rank % host_count, peer=op.peer % host_count)
                elif op.rank >= host_count or op.peer >= host_count:
                    raise SystemExit(
                        f"GOAL rank {op.rank}->{op.peer} does not fit host_count={host_count}; "
                        "use --map-modulo-hosts only for quick smoke tests"
                    )
            if op.rank == op.peer:
                continue
            yield op


def _open_output(path: Path) -> TextIO:
    return sys.stdout if str(path) == "-" else path.open("w", newline="", encoding="utf-8")


def _close_output(path: Path, out: TextIO) -> None:
    if out is not sys.stdout:
        out.close()


def write_trace(path: Path, flows: List[GoalOp], max_flows: int) -> int:
    out = _open_output(path)
    try:
        writer = csv.writer(out)
        writer.writerow(["start_s", "src", "dst", "bytes", "tag", "rank_label"])
        count = 0
        for op in sorted(flows, key=lambda item: (item.start_s, item.rank, item.order)):
            if max_flows > 0 and count >= max_flows:
                break
            writer.writerow(
                [
                    f"{op.start_s:.12g}",
                    op.rank,
                    op.peer,
                    op.size,
                    op.tag,
                    op.label,
                ]
            )
            count += 1
        return count
    finally:
        _close_output(path, out)


def _map_rank_pair(
    rank: int,
    peer: int,
    host_count: Optional[int],
    map_modulo_hosts: bool,
) -> Optional[Tuple[int, int]]:
    if host_count is not None:
        if map_modulo_hosts:
            rank %= host_count
            peer %= host_count
        elif rank >= host_count or peer >= host_count:
            raise SystemExit(
                f"GOAL rank {rank}->{peer} does not fit host_count={host_count}; "
                "use --map-modulo-hosts only for quick smoke tests"
            )
    if rank == peer:
        return None
    return rank, peer


def stream_rank_order_trace(
    input_path: Path,
    output_path: Path,
    host_count: Optional[int],
    map_modulo_hosts: bool,
    max_flows: int,
    stop_after_max_flows: bool,
    rank_sequence_gap_s: float,
) -> Tuple[int, int, int]:
    """Write send flows without building the full GOAL DAG.

    This is useful for large traces when the experiment only needs the real
    communication pairs and sizes, not exact dependency-driven start times.
    """
    num_ranks: Optional[int] = None
    current_rank: Optional[int] = None
    rank_order: Dict[int, int] = {}
    sends_seen = 0
    emitted = 0

    out = _open_output(output_path)
    try:
        writer = csv.writer(out)
        writer.writerow(["start_s", "src", "dst", "bytes", "tag", "rank_label"])
        with input_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line_no, raw in enumerate(f, start=1):
                line = strip_comment(raw)
                if not line:
                    continue

                m = NUM_RANKS_RE.match(line)
                if m:
                    num_ranks = int(m.group(1))
                    continue

                m = RANK_RE.match(line)
                if m:
                    current_rank = int(m.group(1))
                    rank_order.setdefault(current_rank, 0)
                    continue

                if line == "}":
                    current_rank = None
                    continue

                if current_rank is None:
                    continue

                for regex in (SEND_RE, RECV_RE, CALC_RE):
                    m = regex.match(line)
                    if m:
                        rank_order[current_rank] += 1
                        break
                else:
                    if DEP_RE.match(line):
                        continue
                    raise SystemExit(f"{input_path}:{line_no}: unsupported GOAL line: {raw.rstrip()}")

                send = SEND_RE.match(line)
                if not send:
                    continue
                sends_seen += 1
                if int(send.group("size")) == 0:
                    continue
                mapped = _map_rank_pair(
                    current_rank,
                    int(send.group("peer")),
                    host_count,
                    map_modulo_hosts,
                )
                if mapped is None:
                    continue
                src, dst = mapped
                if max_flows > 0 and emitted >= max_flows:
                    if stop_after_max_flows:
                        break
                    continue

                order = rank_order[current_rank] - 1
                start_s = order * rank_sequence_gap_s if rank_sequence_gap_s > 0 else 0.0
                writer.writerow(
                    [
                        f"{start_s:.12g}",
                        src,
                        dst,
                        int(send.group("size")),
                        int(send.group("tag")),
                        send.group("label") or make_auto_label(current_rank, order),
                    ]
                )
                emitted += 1
    finally:
        _close_output(output_path, out)

    if num_ranks is None:
        raise SystemExit(f"{input_path}: missing num_ranks header")
    return num_ranks, sends_seen, emitted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert ATLAHS GOAL text into Nvwa constructor traffic CSV"
    )
    parser.add_argument("-i", "--input", required=True, type=Path, help="Input .goal file")
    parser.add_argument("-o", "--output", required=True, type=Path, help="Output CSV path or '-'")
    parser.add_argument("--host-count", type=int, default=None, help="Validate ranks against host count")
    parser.add_argument(
        "--map-modulo-hosts",
        action="store_true",
        help="Map ranks modulo --host-count. Useful only for smoke tests.",
    )
    parser.add_argument("--max-flows", type=int, default=0, help="Maximum sends to emit")
    parser.add_argument(
        "--schedule-mode",
        default="dag",
        choices=["dag", "rank-order"],
        help="dag honors GOAL dependencies; rank-order streams sends in per-rank order",
    )
    parser.add_argument(
        "--stop-after-max-flows",
        action="store_true",
        help="With --schedule-mode=rank-order, stop scanning after --max-flows emitted flows",
    )
    parser.add_argument(
        "--calc-scale-s-per-unit",
        type=float,
        default=0.0,
        help="Duration assigned to GOAL calc size units",
    )
    parser.add_argument(
        "--op-duration-s",
        type=float,
        default=0.0,
        help="Duration assigned to send/recv nodes for dependency scheduling",
    )
    parser.add_argument(
        "--rank-sequence-gap-s",
        type=float,
        default=0.0,
        help="Minimum gap between consecutive operations in the same rank order",
    )
    args = parser.parse_args()

    if args.schedule_mode == "rank-order":
        num_ranks, sends, emitted = stream_rank_order_trace(
            args.input,
            args.output,
            host_count=args.host_count,
            map_modulo_hosts=args.map_modulo_hosts,
            max_flows=args.max_flows,
            stop_after_max_flows=args.stop_after_max_flows,
            rank_sequence_gap_s=args.rank_sequence_gap_s,
        )
        print(
            f"[OK] mode=rank-order parsed ranks={num_ranks} sends_seen={sends} "
            f"emitted={emitted} output={args.output}",
            file=sys.stderr,
        )
        return 0

    num_ranks, ops_by_rank = parse_goal(args.input)
    schedule_goal(
        ops_by_rank,
        calc_scale_s_per_unit=args.calc_scale_s_per_unit,
        op_duration_s=args.op_duration_s,
        rank_sequence_gap_s=args.rank_sequence_gap_s,
    )
    flows = list(iter_send_flows(ops_by_rank, args.host_count, args.map_modulo_hosts))
    if not flows:
        raise SystemExit(f"{args.input}: no send operations found")

    emitted = write_trace(args.output, flows, args.max_flows)
    print(
        f"[OK] mode=dag parsed ranks={num_ranks} sends={len(flows)} emitted={emitted} output={args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
