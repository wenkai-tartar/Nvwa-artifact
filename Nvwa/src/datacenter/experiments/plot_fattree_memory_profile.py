#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plot figures from fattree_memory_profile_sweep.py outputs.

Examples:
  python3 src/datacenter/experiments/plot_fattree_memory_profile.py

  python3 src/datacenter/experiments/plot_fattree_memory_profile.py \
    --run-dir results/fattree-memory-profile-20260608-015800 \
    --formats pdf,png
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


ROOT = repo_root()

# Keep matplotlib/fontconfig cache inside a writable sandbox-friendly location.
_cache_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "fattree-memory-profile-cache"
_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_dir))
_mpl_config_dir = _cache_dir / "matplotlib"
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import LogLocator  # noqa: E402


plt.rcParams.update({
    "font.size": 18,
    "figure.figsize": (8.5, 5.2),
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.alpha": 0.45,
    "axes.labelsize": 19,
    "xtick.labelsize": 15,
    "ytick.labelsize": 15,
    "legend.fontsize": 14,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


STYLE = {
    "NodeBfs": {"color": "C1", "marker": "s", "label": "ns-3-dc"},
    "NodeBfsWithHost": {"color": "C1", "marker": "D", "label": "ns-3-dc-host"},
    "NodeBfsStrict": {"color": "C3", "marker": "^", "label": "ns-3-dc-strict"},
    "RuleBased": {"color": "C0", "marker": "x", "label": "Nüwa"},
    "Global": {"color": "C2", "marker": "o", "label": "ns-3"},
}


STAGE_LABELS = {
    "topology_build": "Topology",
    "routing_state": "Routing state",
    "other": "Other",
}


STAGE_COLORS = {
    "topology_build": "C0",
    "routing_state": "C1",
    "other": "0.70",
}


COMPARISON_ROUTINGS = ["Global", "NodeBfs", "RuleBased"]


def read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def latest_run_dir() -> Path:
    base = ROOT / "results"
    candidates = [p for p in base.glob("fattree-memory-profile-*") if p.is_dir()]
    if not candidates:
        raise SystemExit("No results/fattree-memory-profile-* directory found. Pass --run-dir.")
    return sorted(candidates, key=lambda p: p.stat().st_mtime)[-1]


def resolve_run_dir(value: Optional[str]) -> Path:
    if value:
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        return path
    return latest_run_dir()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_list(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    values = [x.strip() for x in value.split(",") if x.strip()]
    return values or None


def to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    number = to_float(value)
    if number is None:
        return None
    return int(number)


def case_size_key(row: Dict[str, str]) -> int:
    return to_int(row.get("k")) or 0


def size_label(k: int, hosts: Optional[int]) -> str:
    if hosts is None:
        return f"FT{k}"
    return f"FT{k}\n{hosts} hosts"


def mean(values: Iterable[float]) -> Optional[float]:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return None
    return statistics.fmean(clean)


def stdev(values: Iterable[float]) -> float:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if len(clean) < 2:
        return 0.0
    return statistics.stdev(clean)


def filter_summary_rows(rows: List[Dict[str, str]],
                        routings: Optional[Sequence[str]],
                        include_failed: bool) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    routing_set = set(routings) if routings else None
    for row in rows:
        if routing_set and row.get("routing") not in routing_set:
            continue
        if not include_failed and row.get("rc") not in ("0", 0):
            continue
        out.append(row)
    return out


def sorted_sizes(rows: List[Dict[str, str]]) -> List[int]:
    return sorted({case_size_key(row) for row in rows})


def hosts_by_size(rows: List[Dict[str, str]]) -> Dict[int, int]:
    result: Dict[int, int] = {}
    for row in rows:
        hosts = to_int(row.get("hosts"))
        if hosts is not None:
            result[case_size_key(row)] = hosts
    return result


def routings_in_order(rows: List[Dict[str, str]]) -> List[str]:
    known = [name for name in STYLE if any(row.get("routing") == name for row in rows)]
    extra = sorted({row.get("routing", "") for row in rows if row.get("routing", "") not in STYLE})
    return known + [x for x in extra if x]


def aggregate_summary(rows: List[Dict[str, str]], metric: str) -> Dict[Tuple[str, int], Tuple[Optional[float], float]]:
    groups: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    for row in rows:
        value = to_float(row.get(metric))
        if value is None:
            continue
        groups[(row.get("routing", ""), case_size_key(row))].append(value)
    return {key: (mean(values), stdev(values)) for key, values in groups.items()}


def apply_log_y(ax: plt.Axes) -> None:
    ax.set_yscale("log")
    ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=[0.2, 0.4, 0.6, 0.8], numticks=10))


def save_figure(fig: plt.Figure, out_dir: Path, stem: str, formats: Sequence[str]) -> List[Path]:
    ensure_dir(out_dir)
    paths = []
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        fig.savefig(path, bbox_inches="tight")
        paths.append(path)
    plt.close(fig)
    return paths


def plot_metric(rows: List[Dict[str, str]],
                metric: str,
                ylabel: str,
                out_dir: Path,
                stem: str,
                formats: Sequence[str],
                logy: bool = False) -> List[Path]:
    sizes = sorted_sizes(rows)
    host_map = hosts_by_size(rows)
    labels = [size_label(size, host_map.get(size)) for size in sizes]
    x = list(range(len(sizes)))
    agg = aggregate_summary(rows, metric)

    fig, ax = plt.subplots()
    for routing in routings_in_order(rows):
        style = STYLE.get(routing, {"color": None, "marker": "o", "label": routing})
        xs: List[int] = []
        ys: List[float] = []
        yerrs: List[float] = []
        for idx, size in enumerate(sizes):
            value, err = agg.get((routing, size), (None, 0.0))
            if value is None:
                continue
            if logy and value <= 0:
                continue
            xs.append(idx)
            ys.append(value)
            yerrs.append(err)
        if not xs:
            continue
        ax.errorbar(
            xs,
            ys,
            yerr=yerrs if any(err > 0 for err in yerrs) else None,
            color=style["color"],
            marker=style["marker"],
            linewidth=2,
            markersize=7,
            capsize=3,
            label=style["label"],
        )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0)
    ax.set_ylabel(ylabel)
    if logy:
        apply_log_y(ax)
    ax.legend(loc="best")
    fig.tight_layout()
    return save_figure(fig, out_dir, stem, formats)


def positive_delta(row: Dict[str, str]) -> float:
    value = to_float(row.get("delta_kb"))
    if value is None or value < 0:
        return 0.0
    return value


def aggregate_stages(memory_rows: List[Dict[str, str]],
                     routing: str) -> Tuple[List[int], Dict[int, Dict[str, float]], Dict[int, int]]:
    per_case: Dict[Tuple[str, int], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    hosts: Dict[int, int] = {}

    for row in memory_rows:
        if row.get("routing") != routing:
            continue
        size = case_size_key(row)
        case_id = row.get("case_id", "")
        stage = row.get("stage", "")
        if not case_id or not stage:
            continue
        detail = row.get("detail", "")
        if stage == "traffic_graph" and detail.startswith("hosts="):
            try:
                hosts[size] = int(detail.split("=", 1)[1].split(",", 1)[0])
            except ValueError:
                pass
        bucket = stage if stage in {"topology_build", "routing_state"} else "other"
        per_case[(case_id, size)][bucket] += positive_delta(row)

    per_size_values: Dict[int, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for (_, size), stage_values in per_case.items():
        for stage in ["topology_build", "routing_state", "other"]:
            per_size_values[size][stage].append(stage_values.get(stage, 0.0))

    sizes = sorted(per_size_values)
    aggregated: Dict[int, Dict[str, float]] = {}
    for size in sizes:
        aggregated[size] = {
            stage: (mean(values) or 0.0)
            for stage, values in per_size_values[size].items()
        }
    return sizes, aggregated, hosts


def plot_stage_breakdown(memory_rows: List[Dict[str, str]],
                         routing: str,
                         out_dir: Path,
                         formats: Sequence[str],
                         as_share: bool) -> List[Path]:
    sizes, values, hosts = aggregate_stages(memory_rows, routing)
    if not sizes:
        return []

    stages = ["topology_build", "routing_state", "other"]
    labels = [size_label(size, hosts.get(size)) for size in sizes]
    x = list(range(len(sizes)))
    bottoms = [0.0 for _ in sizes]

    fig, ax = plt.subplots()
    for stage in stages:
        raw = [values[size].get(stage, 0.0) for size in sizes]
        totals = [sum(values[size].get(s, 0.0) for s in stages) for size in sizes]
        if as_share:
            heights = [(v / total * 100.0) if total > 0 else 0.0 for v, total in zip(raw, totals)]
            ylabel = "Initialization RSS delta share (%)"
        else:
            heights = [v / 1024.0 for v in raw]
            ylabel = "Initialization RSS delta (MB)"
        ax.bar(
            x,
            heights,
            bottom=bottoms,
            color=STAGE_COLORS[stage],
            label=STAGE_LABELS[stage],
            width=0.68,
        )
        bottoms = [b + h for b, h in zip(bottoms, heights)]

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0)
    ax.set_ylabel(ylabel)
    ax.set_title(STYLE.get(routing, {"label": routing})["label"])
    ax.legend(loc="best")
    if as_share:
        ax.set_ylim(0, 100)
    fig.tight_layout()
    suffix = "share" if as_share else "delta"
    return save_figure(fig, out_dir, f"stage_breakdown_{routing}_{suffix}", formats)


def plot_routing_comparison_stage_share(summary_rows: List[Dict[str, str]],
                                        memory_rows: List[Dict[str, str]],
                                        out_dir: Path,
                                        formats: Sequence[str]) -> List[Path]:
    available = set(routings_in_order(summary_rows))
    routings = [routing for routing in COMPARISON_ROUTINGS if routing in available]
    if not routings:
        routings = routings_in_order(summary_rows)
    if not routings:
        return []

    stage_data: Dict[Tuple[str, int], Dict[str, float]] = {}
    memory_hosts: Dict[int, int] = {}
    for routing in routings:
        sizes, values, hosts = aggregate_stages(memory_rows, routing)
        memory_hosts.update(hosts)
        for size in sizes:
            stage_data[(routing, size)] = values[size]

    sizes = [
        size for size in sorted_sizes(summary_rows)
        if any((routing, size) in stage_data for routing in routings)
    ]
    if not sizes:
        return []

    host_map = hosts_by_size(summary_rows)
    host_map.update(memory_hosts)
    stages = ["topology_build", "routing_state", "other"]
    bar_width = min(0.22, 0.78 / max(len(routings), 1))
    offsets = [
        (idx - (len(routings) - 1) / 2.0) * bar_width
        for idx in range(len(routings))
    ]

    fig_width = max(8.5, 1.35 * len(sizes) + 2.0)
    fig, ax = plt.subplots(figsize=(fig_width, 5.2))
    bottoms: Dict[Tuple[str, int], float] = defaultdict(float)

    for stage in stages:
        xs: List[float] = []
        heights: List[float] = []
        bottom_values: List[float] = []
        for group_idx, size in enumerate(sizes):
            for routing_idx, routing in enumerate(routings):
                key = (routing, size)
                if key not in stage_data:
                    continue
                total = sum(stage_data[key].get(s, 0.0) for s in stages)
                height = stage_data[key].get(stage, 0.0) / total * 100.0 if total > 0 else 0.0
                xs.append(group_idx + offsets[routing_idx])
                heights.append(height)
                bottom_values.append(bottoms[key])
                bottoms[key] += height
        if not xs:
            continue
        ax.bar(
            xs,
            heights,
            bottom=bottom_values,
            width=bar_width * 0.92,
            color=STAGE_COLORS[stage],
            label=STAGE_LABELS[stage],
        )

    ax.set_xticks(range(len(sizes)))
    ax.set_xticklabels([size_label(size, host_map.get(size)) for size in sizes], rotation=0)
    ax.set_ylabel("Initialization RSS delta share (%)")
    ax.set_xlabel("Within each group: " + ", ".join(routings))
    ax.set_ylim(0, 100)
    ax.set_title("Routing comparison")
    ax.legend(loc="best")
    fig.tight_layout()
    return save_figure(fig, out_dir, "routing_comparison_stage_share", formats)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot FatTree memory profile sweep results.")
    parser.add_argument("--run-dir", default=None, help="Run directory. Defaults to latest results/fattree-memory-profile-*.")
    parser.add_argument("--out-dir", default=None, help="Output directory. Defaults to <run-dir>/figures.")
    parser.add_argument("--formats", default="pdf", help="Comma-separated output formats, e.g. pdf,png.")
    parser.add_argument("--routings", default=None, help="Optional comma-separated routing filter.")
    parser.add_argument("--include-failed", action="store_true", help="Include failed runs in summary plots.")
    args = parser.parse_args()

    run_dir = resolve_run_dir(args.run_dir)
    summary_path = run_dir / "experiment_2_summary.csv"
    memory_path = run_dir / "experiment_2_memory_profile.csv"
    if not summary_path.exists():
        raise SystemExit(f"Missing {summary_path}")
    if not memory_path.exists():
        raise SystemExit(f"Missing {memory_path}")

    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "figures"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    formats = [fmt.strip() for fmt in args.formats.split(",") if fmt.strip()]
    if not formats:
        raise SystemExit("No output formats selected")

    routings = parse_list(args.routings)
    summary_rows = filter_summary_rows(read_csv(summary_path), routings, args.include_failed)
    memory_rows = [row for row in read_csv(memory_path) if not routings or row.get("routing") in set(routings)]
    if not summary_rows:
        raise SystemExit("No summary rows after filtering")

    written: List[Path] = []
    written += plot_metric(
        summary_rows,
        "routing_state_share_pct",
        "Routing-state share (%)",
        out_dir,
        "routing_state_share",
        formats,
    )
    written += plot_metric(
        summary_rows,
        "routing_state_delta_kb",
        "Routing-state RSS delta (KB)",
        out_dir,
        "routing_state_delta",
        formats,
        logy=True,
    )
    written += plot_metric(
        summary_rows,
        "init_peak_mem_gb",
        "Initialization peak memory (GB)",
        out_dir,
        "init_peak_memory",
        formats,
    )
    written += plot_metric(
        summary_rows,
        "exec_peak_mem_gb",
        "Execution peak memory (GB)",
        out_dir,
        "exec_peak_memory",
        formats,
    )
    written += plot_metric(
        summary_rows,
        "routing_entries",
        "Routing entries",
        out_dir,
        "routing_entries",
        formats,
        logy=True,
    )
    written += plot_routing_comparison_stage_share(summary_rows, memory_rows, out_dir, formats)

    for routing in routings_in_order(summary_rows):
        written += plot_stage_breakdown(memory_rows, routing, out_dir, formats, as_share=False)
        written += plot_stage_breakdown(memory_rows, routing, out_dir, formats, as_share=True)

    print(f"[DONE] figures -> {out_dir}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
