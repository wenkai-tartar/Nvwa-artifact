#!/usr/bin/env python3
"""
Extract Nvwa traffic traces from ATLAHS/LogGOPSim binary schedules.

The default mode replays the serialized LogGOPSim DAG far enough to recover
send issue times. It preserves local calc/send/recv dependencies, start
dependencies, LogGOPS resource gaps, message arrival, and eager/rendezvous
receive matching before writing each send as a Nvwa CSV flow:

    start_s,src,dst,bytes,tag,rank_label

Use --schedule-mode=rank-order only for quick traffic-matrix smoke tests; that
legacy mode ignores dependency timing and assigns start_s from local node order.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import mmap
import struct
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, TextIO, Tuple


MAGIC_COOKIE = 4223
OPTYPE_SEND = 1
OPTYPE_RECV = 2
OPTYPE_CALC = 3
EVENT_MSG = 4
NODE_INFO_SIZE = 39
ANY_SOURCE = 0xFFFFFFFF
ANY_TAG = 0xFFFFFFFF


def unpack_from(fmt: str, data: mmap.mmap, offset: int) -> Tuple[int, ...]:
    return struct.unpack_from("<" + fmt, data, offset)


def open_output(path: Path) -> TextIO:
    return sys.stdout if str(path) == "-" else path.open("w", newline="", encoding="utf-8")


def close_output(out: TextIO) -> None:
    if out is not sys.stdout:
        out.close()


def map_rank_pair(
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


@dataclass(frozen=True)
class RankMeta:
    rank_base: int
    rank_end: int
    num_nodes: int
    num_roots: int
    roots_base: int
    nodes_base: int
    appendix_base: int


@dataclass(frozen=True)
class NodeRecord:
    rank: int
    offset: int
    dep_count: int
    op_type: int
    peer: int
    size: int
    tag: int
    proc: int
    nic: int


@dataclass
class Event:
    time: int
    event_type: int
    host: int
    target: int
    size: int
    tag: int
    proc: int
    nic: int
    offset: int
    starttime: int = 0


@dataclass
class QueueElem:
    size: int
    src: int
    tag: int
    offset: int
    proc: int
    starttime: int = 0


class BinarySchedule:
    def __init__(self, data: mmap.mmap, input_path: Path) -> None:
        self.data = data
        self.input_path = input_path
        if len(data) < 8 + 4 + 1 + 1:
            raise SystemExit(f"{input_path}: file is too small to be a serialized GOAL schedule")
        (magic,) = unpack_from("Q", data, 0)
        if magic != MAGIC_COOKIE:
            raise SystemExit(f"{input_path}: missing LogGOPSim magic cookie {MAGIC_COOKIE}")

        self.base = 8
        (self.num_ranks,) = unpack_from("I", data, self.base)
        self.max_cpu = data[self.base + 4]
        self.max_nic = data[self.base + 5]
        self.jump_table = self.base + 4 + 1 + 1
        self._rank_meta: List[RankMeta] = [self._read_rank_meta(rank) for rank in range(self.num_ranks)]

    @property
    def num_cpus(self) -> int:
        return self.max_cpu + 1

    @property
    def num_nics(self) -> int:
        return self.max_nic + 1

    def _read_rank_meta(self, rank: int) -> RankMeta:
        rank_start, rank_end = unpack_from("QQ", self.data, self.jump_table + rank * 16)
        rank_base = self.base + rank_start
        rank_end_abs = self.base + rank_end
        if rank_base + 8 > len(self.data) or rank_end_abs > len(self.data) or rank_base >= rank_end_abs:
            raise SystemExit(f"{self.input_path}: invalid jump table for rank {rank}")
        (num_nodes,) = unpack_from("I", self.data, rank_base)
        (num_roots,) = unpack_from("I", self.data, rank_base + 4)
        roots_base = rank_base + 8
        nodes_base = roots_base + num_roots * 4
        appendix_base = nodes_base + num_nodes * NODE_INFO_SIZE
        if nodes_base > rank_end_abs or appendix_base > rank_end_abs:
            raise SystemExit(f"{self.input_path}: truncated rank {rank} node table")
        return RankMeta(
            rank_base=rank_base,
            rank_end=rank_end_abs,
            num_nodes=num_nodes,
            num_roots=num_roots,
            roots_base=roots_base,
            nodes_base=nodes_base,
            appendix_base=appendix_base,
        )

    def meta(self, rank: int) -> RankMeta:
        return self._rank_meta[rank]

    def root_offsets(self, rank: int) -> Iterable[int]:
        meta = self.meta(rank)
        for idx in range(meta.num_roots):
            (offset,) = unpack_from("I", self.data, meta.roots_base + idx * 4)
            if offset >= meta.num_nodes:
                raise SystemExit(f"{self.input_path}: invalid root offset {offset} in rank {rank}")
            yield offset

    def node_pos(self, rank: int, offset: int) -> int:
        meta = self.meta(rank)
        if offset >= meta.num_nodes:
            raise SystemExit(f"{self.input_path}: invalid node offset {offset} in rank {rank}")
        pos = meta.nodes_base + offset * NODE_INFO_SIZE
        if pos + NODE_INFO_SIZE > meta.rank_end:
            raise SystemExit(f"{self.input_path}: truncated node {rank}:{offset}")
        return pos

    def node(self, rank: int, offset: int) -> NodeRecord:
        pos = self.node_pos(rank, offset)
        (dep_count,) = unpack_from("I", self.data, pos)
        op_type = self.data[pos + 4]
        (peer,) = unpack_from("I", self.data, pos + 5)
        (size,) = unpack_from("Q", self.data, pos + 9)
        (tag,) = unpack_from("I", self.data, pos + 17)
        proc = self.data[pos + 21]
        nic = self.data[pos + 22]
        if proc > self.max_cpu:
            raise SystemExit(f"{self.input_path}: node {rank}:{offset} uses invalid CPU {proc}")
        if nic > self.max_nic:
            raise SystemExit(f"{self.input_path}: node {rank}:{offset} uses invalid NIC {nic}")
        return NodeRecord(
            rank=rank,
            offset=offset,
            dep_count=dep_count,
            op_type=op_type,
            peer=peer,
            size=size,
            tag=tag,
            proc=proc,
            nic=nic,
        )

    def initial_dep_count(self, rank: int, offset: int) -> int:
        pos = self.node_pos(rank, offset)
        (dep_count,) = unpack_from("I", self.data, pos)
        return dep_count

    def _appendix_offsets(self, rank: int, offset: int, count_pos: int, start_pos: int) -> Iterable[int]:
        pos = self.node_pos(rank, offset)
        meta = self.meta(rank)
        (count,) = unpack_from("I", self.data, pos + count_pos)
        (start,) = unpack_from("I", self.data, pos + start_pos)
        if count == 0:
            return
        start_byte = meta.appendix_base + start * 4
        end_byte = start_byte + count * 4
        if start_byte < meta.appendix_base or end_byte > meta.rank_end:
            raise SystemExit(f"{self.input_path}: invalid appendix for rank {rank} node {offset}")
        for idx in range(count):
            (child,) = unpack_from("I", self.data, start_byte + idx * 4)
            if child >= meta.num_nodes:
                raise SystemExit(f"{self.input_path}: invalid child offset {child} in rank {rank}")
            yield child

    def depend_on_me(self, rank: int, offset: int) -> Iterable[int]:
        return self._appendix_offsets(rank, offset, 23, 27)

    def start_depend_on_me(self, rank: int, offset: int) -> Iterable[int]:
        return self._appendix_offsets(rank, offset, 31, 35)


class LogGopsTraceScheduler:
    def __init__(
        self,
        schedule: BinarySchedule,
        output_path: Path,
        host_count: Optional[int],
        map_modulo_hosts: bool,
        max_flows: int,
        max_flows_per_rank: int,
        stop_after_max_flows: bool,
        time_scale_s_per_unit: float,
        loggops_l: int,
        loggops_o: int,
        loggops_g: int,
        loggops_big_g: float,
        loggops_s: int,
        loggops_big_o: int,
        progress_interval: int,
    ) -> None:
        self.schedule = schedule
        self.output_path = output_path
        self.host_count = host_count
        self.map_modulo_hosts = map_modulo_hosts
        self.max_flows = max_flows
        self.max_flows_per_rank = max_flows_per_rank
        self.stop_after_max_flows = stop_after_max_flows
        self.time_scale_s_per_unit = time_scale_s_per_unit
        self.L = loggops_l
        self.o = loggops_o
        self.g = loggops_g
        self.G = loggops_big_g
        self.S = loggops_s
        self.O = loggops_big_o
        self.progress_interval = progress_interval

        ranks = schedule.num_ranks
        self.nexto = [[0] * schedule.num_cpus for _ in range(ranks)]
        self.nextgr = [[0] * schedule.num_nics for _ in range(ranks)]
        self.nextgs = [[0] * schedule.num_nics for _ in range(ranks)]
        self.dep_remaining: List[Dict[int, int]] = [dict() for _ in range(ranks)]
        self.node_start_time: List[Dict[int, int]] = [dict() for _ in range(ranks)]
        self.executable: List[List[Tuple[int, int]]] = [[] for _ in range(ranks)]
        self.rq: List[Dict[Tuple[int, int], Deque[QueueElem]]] = [dict() for _ in range(ranks)]
        self.uq: List[Dict[Tuple[int, int], Deque[QueueElem]]] = [dict() for _ in range(ranks)]
        self.heap: List[Tuple[int, int, Event]] = []
        self.seq = 0
        self.sends_seen = 0
        self.emitted = 0
        self.events_processed = 0
        self.emitted_per_rank = [0] * ranks

    def _bandwidth_cost(self, size: int) -> int:
        return int((size - 1) * self.G)

    def _push_event(self, event: Event) -> None:
        heapq.heappush(self.heap, (event.time, self.seq, event))
        self.seq += 1

    def _queue_push(self, queues: List[Dict[Tuple[int, int], Deque[QueueElem]]], host: int, elem: QueueElem) -> None:
        key = (elem.tag, elem.src)
        q = queues[host].setdefault(key, deque())
        q.append(elem)

    def _queue_match(
        self,
        queues: List[Dict[Tuple[int, int], Deque[QueueElem]]],
        host: int,
        tag: int,
        target: int,
    ) -> Optional[QueueElem]:
        if tag != ANY_TAG and target != ANY_SOURCE:
            q = queues[host].get((tag, target))
            if not q:
                return None
            elem = q.popleft()
            if not q:
                del queues[host][(tag, target)]
            return elem

        for key in sorted(list(queues[host])):
            q = queues[host][key]
            if not q:
                del queues[host][key]
                continue
            q_tag, q_src = key
            if tag not in (ANY_TAG, q_tag) and q_tag != ANY_TAG:
                continue
            if target not in (ANY_SOURCE, q_src) and q_src != ANY_SOURCE:
                continue
            elem = q.popleft()
            if not q:
                del queues[host][key]
            return elem
        return None

    def _current_dep_count(self, rank: int, offset: int) -> int:
        return self.dep_remaining[rank].get(
            offset,
            self.schedule.initial_dep_count(rank, offset),
        )

    def _decrement_dependency(self, rank: int, offset: int) -> bool:
        remaining = self._current_dep_count(rank, offset) - 1
        if remaining < 0:
            raise SystemExit(f"rank {rank}: dependency counter underflow at node {offset}")
        self.dep_remaining[rank][offset] = remaining
        return remaining == 0

    def _mark_node_as_started(self, rank: int, offset: int) -> None:
        for child in self.schedule.start_depend_on_me(rank, offset):
            if self._decrement_dependency(rank, child):
                self.executable[rank].append((child, 0))

    def _mark_node_as_done(self, rank: int, offset: int, cpu_time: int) -> None:
        for child in self.schedule.depend_on_me(rank, offset):
            previous = self.node_start_time[rank].get(child)
            if previous is None or cpu_time > previous:
                self.node_start_time[rank][child] = cpu_time
            if self._decrement_dependency(rank, child):
                start_time = self.node_start_time[rank].pop(child, 0)
                self.executable[rank].append((child, start_time))

    def _make_node_event(self, rank: int, offset: int, start_time: int, initial: bool) -> Event:
        node = self.schedule.node(rank, offset)
        if node.op_type not in (OPTYPE_SEND, OPTYPE_RECV, OPTYPE_CALC):
            raise SystemExit(f"rank {rank}: unsupported node type {node.op_type} at offset {offset}")
        if initial:
            event_time = 0
        elif node.op_type == OPTYPE_CALC:
            event_time = max(start_time, self.nexto[rank][node.proc])
        elif node.op_type == OPTYPE_SEND:
            event_time = max(start_time, self.nextgs[rank][node.nic])
        else:
            event_time = start_time
        return Event(
            time=event_time,
            event_type=node.op_type,
            host=rank,
            target=node.peer,
            size=node.size,
            tag=node.tag,
            proc=node.proc,
            nic=node.nic,
            offset=node.offset,
            starttime=start_time,
        )

    def _push_newly_executable(self, hosts: Iterable[int]) -> None:
        for host in hosts:
            pending = self.executable[host]
            self.executable[host] = []
            for offset, start_time in pending:
                self._push_event(self._make_node_event(host, offset, start_time, initial=False))

    def _initialize_roots(self) -> None:
        for rank in range(self.schedule.num_ranks):
            for offset in self.schedule.root_offsets(rank):
                self._push_event(self._make_node_event(rank, offset, 0, initial=True))

    def _emit_send(self, writer: csv.writer, event: Event, original_size: int) -> None:
        self.sends_seen += 1
        if original_size == 0:
            return
        mapped = map_rank_pair(event.host, event.target, self.host_count, self.map_modulo_hosts)
        if mapped is None:
            return
        if self.max_flows_per_rank > 0 and self.emitted_per_rank[event.host] >= self.max_flows_per_rank:
            return
        if self.max_flows > 0 and self.emitted >= self.max_flows:
            return

        src, dst = mapped
        writer.writerow(
            [
                f"{event.time * self.time_scale_s_per_unit:.12g}",
                src,
                dst,
                original_size,
                event.tag,
                f"rank{event.host}_node{event.offset}",
            ]
        )
        self.emitted += 1
        self.emitted_per_rank[event.host] += 1

    def _sampling_complete(self) -> bool:
        if self.max_flows > 0 and self.stop_after_max_flows and self.emitted >= self.max_flows:
            return True
        if self.max_flows_per_rank > 0 and all(
            count >= self.max_flows_per_rank for count in self.emitted_per_rank
        ):
            return True
        return False

    def _process_locop(self, event: Event) -> List[int]:
        if self.nexto[event.host][event.proc] <= event.time:
            cpu_time = event.time + event.size
            self.nexto[event.host][event.proc] = cpu_time
            self._mark_node_as_started(event.host, event.offset)
            self._mark_node_as_done(event.host, event.offset, cpu_time)
            return [event.host]

        event.time = self.nexto[event.host][event.proc]
        self._push_event(event)
        return []

    def _process_send(self, writer: csv.writer, event: Event) -> List[int]:
        resource_time = max(self.nexto[event.host][event.proc], self.nextgs[event.host][event.nic])
        if resource_time > event.time:
            event.time = resource_time
            self._push_event(event)
            return []

        self._mark_node_as_started(event.host, event.offset)
        check_hosts = [event.host]
        original_size = event.size
        if event.size == 0:
            event.size = 1
        bandwidth_cost = self._bandwidth_cost(event.size)
        cpu_time = event.time + self.o + (event.size - 1) * self.O
        self.nexto[event.host][event.proc] = cpu_time
        self.nextgs[event.host][event.nic] = event.time + self.g + bandwidth_cost
        self._emit_send(writer, event, original_size)

        msg = Event(
            time=cpu_time + self.L + bandwidth_cost,
            event_type=EVENT_MSG,
            host=event.target,
            target=event.host,
            size=event.size,
            tag=event.tag,
            proc=event.proc,
            nic=event.nic,
            offset=event.offset,
            starttime=event.time,
        )
        self._push_event(msg)

        if event.size <= self.S:
            self._mark_node_as_done(event.host, event.offset, cpu_time)
        return check_hosts

    def _process_recv(self, event: Event) -> List[int]:
        self._mark_node_as_started(event.host, event.offset)
        check_hosts = [event.host]
        if event.size == 0:
            event.size = 1

        matched = self._queue_match(self.uq, event.host, event.tag, event.target)
        if matched is None:
            self._queue_push(
                self.rq,
                event.host,
                QueueElem(
                    size=event.size,
                    src=event.target,
                    tag=event.tag,
                    offset=event.offset,
                    proc=event.proc,
                ),
            )
            return check_hosts

        nic_time = max(self.nextgs[event.host][event.nic], event.time) + self.g
        cpu_time = nic_time + self.o + (event.size - 1) * self.O
        self.nexto[event.host][event.proc] = cpu_time
        self.nextgr[event.host][event.nic] = nic_time

        if event.size > self.S:
            self._mark_node_as_done(matched.src, matched.offset, cpu_time)
            check_hosts.append(matched.src)
            if self.nexto[matched.src][event.proc] < cpu_time:
                self.nexto[matched.src][event.proc] = cpu_time
            if self.nextgs[matched.src][event.nic] < nic_time:
                self.nextgs[matched.src][event.nic] = nic_time

        self._mark_node_as_done(event.host, event.offset, cpu_time)
        return check_hosts

    def _process_msg(self, event: Event) -> List[int]:
        if event.size == 0:
            event.size = 1

        matched = self._queue_match(self.rq, event.host, event.tag, event.target)
        if matched is None:
            self._queue_push(
                self.uq,
                event.host,
                QueueElem(
                    size=event.size,
                    src=event.target,
                    tag=event.tag,
                    offset=event.offset,
                    proc=event.proc,
                    starttime=event.time,
                ),
            )
            return []

        cpu = matched.proc
        resource_time = max(self.nexto[event.host][cpu], self.nextgr[event.host][event.nic])
        if resource_time > event.time:
            event.time = resource_time
            self._push_event(event)
            self._queue_push(self.rq, event.host, matched)
            return []

        nic_time = max(self.nextgr[event.host][event.nic], event.time) + self.g
        cpu_time = nic_time + self.o + (event.size - 1) * self.O
        self.nexto[event.host][cpu] = cpu_time
        self.nextgr[event.host][event.nic] = nic_time

        check_hosts = [event.host]
        if event.size > self.S:
            self._mark_node_as_done(event.target, event.offset, cpu_time)
            check_hosts.append(event.target)
            if self.nexto[event.target][event.proc] < cpu_time:
                self.nexto[event.target][event.proc] = cpu_time
            if self.nextgs[event.target][event.nic] < nic_time:
                self.nextgs[event.target][event.nic] = nic_time

        self._mark_node_as_done(event.host, matched.offset, cpu_time)
        return check_hosts

    def run(self) -> Tuple[int, int, int]:
        if self.host_count is not None and not self.map_modulo_hosts and self.schedule.num_ranks > self.host_count:
            raise SystemExit(
                f"GOAL ranks={self.schedule.num_ranks} do not fit host_count={self.host_count}; "
                "use --map-modulo-hosts only for quick smoke tests"
            )

        out = open_output(self.output_path)
        try:
            writer = csv.writer(out)
            writer.writerow(["start_s", "src", "dst", "bytes", "tag", "rank_label"])
            self._initialize_roots()

            while self.heap:
                _, _, event = heapq.heappop(self.heap)
                if event.event_type == OPTYPE_CALC:
                    check_hosts = self._process_locop(event)
                elif event.event_type == OPTYPE_SEND:
                    check_hosts = self._process_send(writer, event)
                elif event.event_type == OPTYPE_RECV:
                    check_hosts = self._process_recv(event)
                elif event.event_type == EVENT_MSG:
                    check_hosts = self._process_msg(event)
                else:
                    raise SystemExit(f"unsupported event type {event.event_type}")

                self.events_processed += 1
                if check_hosts:
                    self._push_newly_executable(set(check_hosts))
                if self.progress_interval > 0 and self.events_processed % self.progress_interval == 0:
                    print(
                        "[progress] "
                        f"events={self.events_processed} sends_seen={self.sends_seen} "
                        f"emitted={self.emitted} heap={len(self.heap)}",
                        file=sys.stderr,
                    )
                if self._sampling_complete():
                    break
        finally:
            close_output(out)

        return self.schedule.num_ranks, self.sends_seen, self.emitted


def stream_rank_order_trace(
    schedule: BinarySchedule,
    output_path: Path,
    host_count: Optional[int],
    map_modulo_hosts: bool,
    max_flows: int,
    max_flows_per_rank: int,
    stop_after_max_flows: bool,
    rank_sequence_gap_s: float,
) -> Tuple[int, int, int]:
    sends_seen = 0
    emitted = 0

    out = open_output(output_path)
    try:
        writer = csv.writer(out)
        writer.writerow(["start_s", "src", "dst", "bytes", "tag", "rank_label"])

        for rank in range(schedule.num_ranks):
            emitted_for_rank = 0
            meta = schedule.meta(rank)
            for offset in range(meta.num_nodes):
                node = schedule.node(rank, offset)
                if node.op_type != OPTYPE_SEND:
                    continue
                sends_seen += 1
                if node.size == 0:
                    continue
                mapped = map_rank_pair(rank, node.peer, host_count, map_modulo_hosts)
                if mapped is None:
                    continue
                if max_flows_per_rank > 0 and emitted_for_rank >= max_flows_per_rank:
                    continue
                if max_flows > 0 and emitted >= max_flows:
                    if stop_after_max_flows:
                        return schedule.num_ranks, sends_seen, emitted
                    continue

                src, dst = mapped
                start_s = offset * rank_sequence_gap_s if rank_sequence_gap_s > 0 else 0.0
                writer.writerow(
                    [
                        f"{start_s:.12g}",
                        src,
                        dst,
                        node.size,
                        node.tag,
                        f"rank{rank}_node{offset}",
                    ]
                )
                emitted += 1
                emitted_for_rank += 1
    finally:
        close_output(out)

    return schedule.num_ranks, sends_seen, emitted


def convert(
    input_path: Path,
    output_path: Path,
    schedule_mode: str,
    host_count: Optional[int],
    map_modulo_hosts: bool,
    max_flows: int,
    max_flows_per_rank: int,
    stop_after_max_flows: bool,
    rank_sequence_gap_s: float,
    time_scale_s_per_unit: float,
    loggops_l: int,
    loggops_o: int,
    loggops_g: int,
    loggops_big_g: float,
    loggops_s: int,
    loggops_big_o: int,
    progress_interval: int,
) -> Tuple[int, int, int]:
    if not input_path.exists():
        raise SystemExit(
            f"{input_path}: input trace does not exist. "
            "Check that $GROK_BIN is set in this shell."
        )
    if not input_path.is_file():
        raise SystemExit(
            f"{input_path}: input trace is not a file. "
            "If this printed '.', $GROK_BIN is empty or unset in this shell."
        )

    with input_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            schedule = BinarySchedule(data, input_path)
            if schedule_mode == "rank-order":
                return stream_rank_order_trace(
                    schedule,
                    output_path,
                    host_count=host_count,
                    map_modulo_hosts=map_modulo_hosts,
                    max_flows=max_flows,
                    max_flows_per_rank=max_flows_per_rank,
                    stop_after_max_flows=stop_after_max_flows,
                    rank_sequence_gap_s=rank_sequence_gap_s,
                )

            scheduler = LogGopsTraceScheduler(
                schedule,
                output_path=output_path,
                host_count=host_count,
                map_modulo_hosts=map_modulo_hosts,
                max_flows=max_flows,
                max_flows_per_rank=max_flows_per_rank,
                stop_after_max_flows=stop_after_max_flows,
                time_scale_s_per_unit=time_scale_s_per_unit,
                loggops_l=loggops_l,
                loggops_o=loggops_o,
                loggops_g=loggops_g,
                loggops_big_g=loggops_big_g,
                loggops_s=loggops_s,
                loggops_big_o=loggops_big_o,
                progress_interval=progress_interval,
            )
            return scheduler.run()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert ATLAHS/LogGOPSim binary schedules into Nvwa constructor traffic CSV"
    )
    parser.add_argument("-i", "--input", required=True, type=Path, help="Input .bin schedule")
    parser.add_argument("-o", "--output", required=True, type=Path, help="Output CSV path or '-'")
    parser.add_argument(
        "--schedule-mode",
        default="loggops",
        choices=["loggops", "rank-order"],
        help="loggops replays the serialized DAG timing; rank-order is a quick legacy scan",
    )
    parser.add_argument("--host-count", type=int, default=None, help="Validate ranks against host count")
    parser.add_argument(
        "--map-modulo-hosts",
        action="store_true",
        help="Map ranks modulo --host-count. Useful only for smoke tests.",
    )
    parser.add_argument("--max-flows", type=int, default=0, help="Maximum sends to emit")
    parser.add_argument(
        "--max-flows-per-rank",
        type=int,
        default=0,
        help="Maximum sends to emit from each original rank (0 means unlimited)",
    )
    parser.add_argument(
        "--stop-after-max-flows",
        action="store_true",
        help="Stop simulation/scanning after --max-flows emitted flows",
    )
    parser.add_argument(
        "--rank-sequence-gap-s",
        type=float,
        default=0.0,
        help="Legacy per-node start gap used only by --schedule-mode=rank-order",
    )
    parser.add_argument(
        "--time-scale-s-per-unit",
        type=float,
        default=1e-9,
        help="Seconds per LogGOPSim time unit when writing start_s",
    )
    parser.add_argument("--loggops-l", type=int, default=2500, metavar="L", help="LogGOPS latency L")
    parser.add_argument("--loggops-o", type=int, default=1500, metavar="o", help="LogGOPS overhead o")
    parser.add_argument("--loggops-g", type=int, default=1000, metavar="g", help="LogGOPS per-message gap g")
    parser.add_argument("--loggops-G", type=float, default=6.0, metavar="G", help="LogGOPS per-byte gap G")
    parser.add_argument("--loggops-S", type=int, default=65535, metavar="S", help="Eager/rendezvous threshold S")
    parser.add_argument("--loggops-O", type=int, default=0, metavar="O", help="LogGOPS per-byte overhead O")
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=0,
        help="Print progress every N processed events in loggops mode",
    )
    args = parser.parse_args()

    num_ranks, sends, emitted = convert(
        args.input,
        args.output,
        schedule_mode=args.schedule_mode,
        host_count=args.host_count,
        map_modulo_hosts=args.map_modulo_hosts,
        max_flows=args.max_flows,
        max_flows_per_rank=args.max_flows_per_rank,
        stop_after_max_flows=args.stop_after_max_flows,
        rank_sequence_gap_s=args.rank_sequence_gap_s,
        time_scale_s_per_unit=args.time_scale_s_per_unit,
        loggops_l=args.loggops_l,
        loggops_o=args.loggops_o,
        loggops_g=args.loggops_g,
        loggops_big_g=args.loggops_G,
        loggops_s=args.loggops_S,
        loggops_big_o=args.loggops_O,
        progress_interval=args.progress_interval,
    )
    print(
        f"[OK] mode={args.schedule_mode} parsed ranks={num_ranks} "
        f"sends_seen={sends} emitted={emitted} output={args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
