#!/usr/bin/env python3
import argparse
import csv
import math
import os
from collections import defaultdict
from pathlib import Path
from statistics import fmean

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "nvwa-ae-matplotlib"))

import matplotlib

from plot_style import configure_matplotlib

configure_matplotlib(matplotlib)
matplotlib.use("Agg")
import matplotlib.pyplot as plt


FINE_COMPONENTS = [
    {
        "field": "bfs_route_compute_s",
        "pct_field": "bfs_route_compute_pct",
        "label": "BFS computation",
        "color": "#F58518",
        "hatch": "////",
    },
    {
        "field": "route_table_install_s",
        "pct_field": "route_table_install_pct",
        "label": "Table installation",
        "color": "#4C78A8",
        "hatch": "",
    },
    {
        "field": "other_s",
        "pct_field": "other_pct",
        "label": "Others",
        "color": "#54A24B",
        "hatch": "",
    },
]

COARSE_COMPONENTS = [
    {
        "field": "topology_build_s",
        "pct_field": "topology_pct",
        "label": "Topology build",
        "color": "#4C78A8",
        "hatch": "",
    },
    {
        "field": "routing_computation_s",
        "pct_field": "routing_pct",
        "label": "Routing computation",
        "color": "#F58518",
        "hatch": "////",
    },
    {
        "field": "other_s",
        "pct_field": "other_pct",
        "label": "Others",
        "color": "#54A24B",
        "hatch": "",
    },
]

FIGSIZE = (3.85, 2.35)
LEGEND_FONTSIZE = 8.2
LABEL_FONTSIZE = 9.5
TICK_FONTSIZE = 8.0
ANNOTATION_FONTSIZE = 7.8
BAR_WIDTH = 0.62
BAR_LINEWIDTH = 0.5
GRID_ALPHA = 0.45
LEGEND_COLUMN_SPACING = 0.75
LEGEND_HANDLE_LENGTH = 1.1

BASE_STATS_FIELDS = [
    "k",
    "fat_tree",
    "routing",
    "repeat_count",
    "hosts",
    "routing_entries",
    "init_total_s",
]

FINE_STATS_FIELDS = BASE_STATS_FIELDS + [
    "bfs_route_compute_s",
    "route_table_install_s",
    "other_s",
    "bfs_route_compute_pct",
    "route_table_install_pct",
    "other_pct",
]

COARSE_STATS_FIELDS = BASE_STATS_FIELDS + [
    "topology_build_s",
    "routing_computation_s",
    "other_s",
    "topology_pct",
    "routing_pct",
    "other_pct",
]

FINE_INPUT_FIELDS = {
    "bfs_route_compute_s": "node_bfs_route_compute_s",
    "route_table_install_s": "node_bfs_route_table_install_s",
    "other_s": "node_bfs_other_s",
    "bfs_route_compute_pct": "node_bfs_route_compute_pct",
    "route_table_install_pct": "node_bfs_route_table_install_pct",
    "other_pct": "node_bfs_other_pct",
}
COARSE_INPUT_FIELDS: dict[str, str] = {}
DEFAULT_TIME_BREAKDOWN_NAME = "experiment_3_time_breakdown.csv"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def number(value: object, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def mean(values: list[float | None]) -> float:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(clean) if clean else 0.0


def save(fig, out_dir: Path, name: str, formats: list[str]) -> list[Path]:
    paths = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        paths.append(path)
    plt.close(fig)
    return paths


def select_breakdown_schema(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], dict[str, str]]:
    fieldnames = set().union(*(row.keys() for row in rows))
    fine_fields = set(FINE_INPUT_FIELDS.values())
    coarse_fields = {
        "topology_build_s",
        "routing_computation_s",
        "other_s",
        "topology_pct",
        "routing_pct",
        "other_pct",
    }
    if fine_fields <= fieldnames:
        return FINE_COMPONENTS, FINE_STATS_FIELDS, FINE_INPUT_FIELDS
    if coarse_fields <= fieldnames:
        return COARSE_COMPONENTS, COARSE_STATS_FIELDS, COARSE_INPUT_FIELDS
    raise SystemExit("time-breakdown CSV lacks both fine NodeBfs and coarse timing breakdown columns")


def summarize(
    rows: list[dict[str, str]],
    stats_fields: list[str],
    input_fields: dict[str, str],
) -> list[dict[str, str]]:
    buckets: dict[int, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    metadata: dict[int, dict[str, str]] = {}

    for row in rows:
        routing = row.get("routing", "")
        if not routing.startswith("NodeBfs"):
            continue
        k_value = number(row.get("k"))
        if k_value is None:
            continue
        k = int(k_value)
        metadata.setdefault(k, {"routing": routing, "hosts": row.get("hosts", "")})
        if row.get("routing_entries"):
            metadata[k]["routing_entries"] = row.get("routing_entries", "")
        for field in stats_fields:
            if field in {"k", "fat_tree", "routing", "repeat_count", "hosts", "routing_entries"}:
                continue
            input_field = input_fields.get(field, field)
            buckets[k][field].append(number(row.get(input_field)))

    if not buckets:
        raise SystemExit("No NodeBfs rows found in the time-breakdown CSV")

    out_rows = []
    for k in sorted(buckets):
        metrics = buckets[k]
        meta = metadata.get(k, {})
        out_row = {
            "k": str(k),
            "fat_tree": f"FT{k}",
            "routing": meta.get("routing", "NodeBfs"),
            "repeat_count": str(len(metrics["init_total_s"])),
            "hosts": meta.get("hosts", ""),
            "routing_entries": meta.get("routing_entries", ""),
            "init_total_s": f"{mean(metrics['init_total_s']):.6f}",
        }
        for field in stats_fields:
            if field in out_row:
                continue
            decimals = 2 if field.endswith("_pct") else 6
            out_row[field] = f"{mean(metrics[field]):.{decimals}f}"
        out_rows.append(out_row)
    return out_rows


def values(rows: list[dict[str, str]], field: str) -> list[float]:
    return [number(row.get(field), 0.0) or 0.0 for row in rows]


def labels(rows: list[dict[str, str]]) -> list[str]:
    return [row["fat_tree"] for row in rows]


def plot_figure1c(
    rows: list[dict[str, str]],
    out_dir: Path,
    formats: list[str],
    components: list[dict[str, str]],
) -> list[Path]:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = list(range(len(rows)))
    bottoms = [0.0] * len(rows)
    for component in components:
        vals = values(rows, component["pct_field"])
        ax.bar(
            x,
            vals,
            bottom=bottoms,
            width=BAR_WIDTH,
            label=component["label"],
            color=component["color"],
            hatch=component["hatch"],
            edgecolor="black",
            linewidth=BAR_LINEWIDTH,
            zorder=3,
        )
        bottoms = [bottom + value for bottom, value in zip(bottoms, vals)]

    for idx, row in enumerate(rows):
        total_s = number(row.get("init_total_s"), 0.0) or 0.0
        if total_s < 1.0:
            label = f"{total_s * 1000.0:.1f} ms"
        elif total_s >= 100.0:
            label = f"{total_s:.1f} s"
        else:
            label = f"{total_s:.2f} s"
        ax.text(idx, 103.0, label, ha="center", va="bottom", fontsize=ANNOTATION_FONTSIZE)

    ax.set_xticks(x, labels(rows))
    ax.tick_params(axis="x", labelsize=TICK_FONTSIZE)
    ax.tick_params(axis="y", labelsize=TICK_FONTSIZE)
    ax.set_xlabel("Fat-tree scale (k)", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("Init. time composition (%)", fontsize=LABEL_FONTSIZE)
    ax.set_ylim(0, 118)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="--", alpha=GRID_ALPHA, zorder=0)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.legend(
        handles,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        ncol=3,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        columnspacing=LEGEND_COLUMN_SPACING,
        handlelength=LEGEND_HANDLE_LENGTH,
    )
    return save(fig, out_dir, "figure1c", formats)


def parse_formats(text: str) -> list[str]:
    formats = [part.strip().lstrip(".") for part in text.split(",") if part.strip()]
    if not formats:
        raise SystemExit("No output formats selected")
    return formats


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot paper Figure 1(c).")
    parser.add_argument("--run-dir", required=True, help="Experiment 7 result directory.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--time-breakdown-name", default=DEFAULT_TIME_BREAKDOWN_NAME)
    parser.add_argument("--formats", default="pdf,png")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    breakdown_path = run_dir / args.time_breakdown_name
    if not breakdown_path.exists():
        raise SystemExit(f"Missing NodeBfs breakdown CSV: {breakdown_path}")

    raw_rows = read_csv(breakdown_path)
    components, stats_fields, input_fields = select_breakdown_schema(raw_rows)
    stats = summarize(raw_rows, stats_fields, input_fields)
    stats_path = out_dir / "figure1c_initialization_time_profile.csv"
    write_csv(stats_path, stats_fields, stats)

    formats = parse_formats(args.formats)
    written: list[Path] = [stats_path]
    written += plot_figure1c(stats, out_dir, formats, components)

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
