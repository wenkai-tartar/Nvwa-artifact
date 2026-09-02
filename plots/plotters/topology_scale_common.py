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
from matplotlib.lines import Line2D


TOPOLOGIES = [
    {
        "key": "fattree",
        "title": "Fattree",
        "scale_name": "k",
        "label_prefix": "FT",
        "stats_name": "experiment_1.csv",
        "latest_pointer": "latest_fattree_ring_allreduce.txt",
        "current_pointer": "current_experiment1_fattree_ring_allreduce.txt",
        "glob": "experiment1_fattree_ring_allreduce_*/experiment_1.csv",
    },
    {
        "key": "dragonfly",
        "title": "Dragonfly",
        "scale_name": "h",
        "label_prefix": "DF",
        "stats_name": "experiment_4.csv",
        "latest_pointer": "latest_dragonfly_ring_allreduce.txt",
        "current_pointer": "current_experiment2_dragonfly_ring_allreduce.txt",
        "glob": "experiment2_dragonfly_ring_allreduce_*/experiment_4.csv",
    },
    {
        "key": "torus",
        "title": "Torus",
        "scale_name": "d",
        "label_prefix": "TR",
        "stats_name": "experiment_5.csv",
        "latest_pointer": "latest_torus_ring_allreduce.txt",
        "current_pointer": "current_experiment3_torus_ring_allreduce.txt",
        "glob": "experiment3_torus_ring_allreduce_*/experiment_5.csv",
    },
]


SYSTEMS = [
    {
        "key": "nvwa",
        "label": "N\u00fcwa",
        "routings": {"RuleBased"},
        "color": "#1f77b4",
        "marker": "^",
    },
    {
        "key": "ns3dc",
        "label": "ns-3-dc",
        "routings": {"NodeBfs", "NodeBfsWithHost"},
        "color": "#ff7f0e",
        "marker": "s",
    },
    {
        "key": "ns3",
        "label": "ns-3",
        "routings": {"Global"},
        "color": "#2ca02c",
        "marker": "o",
    },
]

SYSTEM_BY_KEY = {str(system["key"]): system for system in SYSTEMS}
PLOT_ORDER = ["ns3", "ns3dc", "nvwa"]
SYSTEM_ZORDER = {"ns3": 3, "ns3dc": 4, "nvwa": 5}


METRICS = {
    "memory": {
        "field": "exec_mem_gb",
        "ylabel": "Execution memory (GB)",
        "log": False,
    },
    "init": {
        "field": "init_time_s",
        "ylabel": "Initialization time (s)",
        "log": True,
    },
    "exec": {
        "field": "exec_time_s",
        "ylabel": "Execution time (s)",
        "log": False,
    },
    "total": {
        "field": "total_time_s",
        "ylabel": "Total simulation time (s)",
        "log": True,
    },
}


FIGURE_SPECS = {
    "figure8a": {
        "topology": "fattree",
        "metric": "memory",
        "xlabel": "(a) Fattree",
        "csv": "figure8a_memory_fattree.csv",
    },
    "figure8b": {
        "topology": "dragonfly",
        "metric": "memory",
        "xlabel": "(b) Dragonfly",
        "csv": "figure8b_memory_dragonfly.csv",
    },
    "figure8c": {
        "topology": "torus",
        "metric": "memory",
        "xlabel": "(c) Torus",
        "csv": "figure8c_memory_torus.csv",
    },
    "figure9a": {
        "topology": "fattree",
        "metric": "init",
        "xlabel": "(a) Fattree",
        "csv": "figure9a_initialization_time_fattree.csv",
    },
    "figure9b": {
        "topology": "dragonfly",
        "metric": "init",
        "xlabel": "(b) Dragonfly",
        "csv": "figure9b_initialization_time_dragonfly.csv",
    },
    "figure9c": {
        "topology": "torus",
        "metric": "init",
        "xlabel": "(c) Torus",
        "csv": "figure9c_initialization_time_torus.csv",
    },
    "figure10a": {
        "topology": "fattree",
        "metric": "exec",
        "xlabel": "(a) Fattree execution",
        "csv": "figure10a_execution_time_fattree.csv",
        "max_scale": 64,
    },
    "figure10b": {
        "topology": "dragonfly",
        "metric": "exec",
        "xlabel": "(b) Dragonfly execution",
        "csv": "figure10b_execution_time_dragonfly.csv",
    },
    "figure10c": {
        "topology": "torus",
        "metric": "exec",
        "xlabel": "(c) Torus execution",
        "csv": "figure10c_execution_time_torus.csv",
    },
    "figure10d": {
        "topology": "fattree",
        "metric": "total",
        "xlabel": "(d) Fattree total",
        "csv": "figure10d_total_time_fattree.csv",
    },
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def number(value, default=None):
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def mean(values):
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(clean) if clean else None


def system_for_routing(routing):
    for system in SYSTEMS:
        if routing in system["routings"]:
            return system
    return None


def resolve_stats_path(results_root, explicit_path, topology):
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if path.is_dir():
            path = path / topology["stats_name"]
        path = path.resolve()
        if not path.exists():
            raise SystemExit(f"stats file not found: {path}")
        return path

    for pointer_name in (topology["latest_pointer"], topology["current_pointer"]):
        pointer = results_root / pointer_name
        if not pointer.exists():
            continue
        target_text = pointer.read_text(encoding="utf-8").strip()
        if not target_text:
            continue
        target = Path(target_text).expanduser()
        if not target.is_absolute():
            target = (pointer.parent / target).resolve()
        stats_path = target / topology["stats_name"] if target.is_dir() else target
        if stats_path.exists():
            return stats_path.resolve()

    candidates = sorted(
        results_root.glob(topology["glob"]),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0].resolve()
    raise SystemExit(f"cannot find {topology['stats_name']} under {results_root}")


def total_time(row):
    wall = number(row.get("wall_s"))
    if wall is not None:
        return wall
    init_time = number(row.get("init_time_s"), 0.0)
    exec_time = number(row.get("exec_time_s"), 0.0)
    if init_time is None or exec_time is None:
        return None
    return init_time + exec_time


def load_topology_stats(topology, stats_path):
    buckets = defaultdict(lambda: defaultdict(list))
    routings = defaultdict(set)
    raw_rows = read_csv(stats_path)
    for row in raw_rows:
        routing = row.get("routing", "")
        system = system_for_routing(routing)
        if system is None:
            continue
        scale = number(row.get("scale_value"))
        if scale is None:
            continue
        scale = int(scale)
        key = (topology["key"], system["key"], scale)
        routings[key].add(routing)
        for field in ("init_time_s", "init_mem_gb", "exec_time_s", "exec_mem_gb", "wall_s", "hosts"):
            buckets[key][field].append(number(row.get(field)))
        buckets[key]["total_time_s"].append(total_time(row))
        buckets[key]["repeat_count"].append(number(row.get("repeat_count"), 1.0))

    rows = []
    for (topology_key, system_key, scale), metrics in sorted(buckets.items()):
        system = next(item for item in SYSTEMS if item["key"] == system_key)
        out = {
            "topology": topology_key,
            "scale_name": topology["scale_name"],
            "scale_value": scale,
            "scale_label": f"{topology['label_prefix']}{scale}",
            "system": system["label"],
            "system_key": system_key,
            "routing": ",".join(sorted(routings[(topology_key, system_key, scale)])),
            "source": str(stats_path),
        }
        for field in ("init_time_s", "init_mem_gb", "exec_time_s", "exec_mem_gb", "wall_s", "total_time_s", "hosts"):
            out[field] = mean(metrics[field])
        out["repeat_count"] = int(sum(value for value in metrics["repeat_count"] if value is not None))
        rows.append(out)
    return rows


def format_cell(value):
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_normalized_stats(rows, out_dir, name):
    fields = [
        "topology",
        "scale_name",
        "scale_value",
        "scale_label",
        "system",
        "routing",
        "init_time_s",
        "init_mem_gb",
        "exec_time_s",
        "exec_mem_gb",
        "wall_s",
        "total_time_s",
        "hosts",
        "repeat_count",
        "source",
    ]
    path = out_dir / name
    formatted = [{field: format_cell(row.get(field)) for field in fields} for row in rows]
    write_csv(path, fields, formatted)
    return path


def rows_by_topology(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["topology"]].append(row)
    return grouped


def row_lookup(rows):
    return {(row["topology"], row["system_key"], row["scale_value"]): row for row in rows}


def topology_scales(rows, topology_key):
    return sorted({row["scale_value"] for row in rows if row["topology"] == topology_key})


def metric_values(rows, topology_key, metric):
    field = METRICS[metric]["field"]
    return [
        row[field]
        for row in rows
        if row["topology"] == topology_key and row.get(field) is not None
    ]


def apply_axis_style(ax, values, log_scale):
    ax.grid(True, which="major", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.grid(True, which="minor", color="#eeeeee", linewidth=0.5, alpha=0.55)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)

    if log_scale:
        positive = [value for value in values if value is not None and value > 0]
        ax.set_yscale("log")
        if positive:
            bottom = 10 ** math.floor(math.log10(min(positive)))
            top = 10 ** math.ceil(math.log10(max(positive)))
            if bottom == top:
                top *= 10
            ax.set_ylim(bottom, top)
    else:
        clean = [value for value in values if value is not None]
        if clean:
            top = max(clean)
            ax.set_ylim(bottom=0.0, top=top * 1.12 if top > 0 else 1.0)


def plot_metric_axis(ax, rows, topology, metric, panel_label=None):
    metric_spec = METRICS[metric]
    lookup = row_lookup(rows)
    scales = topology_scales(rows, topology["key"])
    positions = {scale: idx for idx, scale in enumerate(scales)}
    present_system_keys = []

    for system in SYSTEMS:
        system_key = str(system["key"])
        for scale in scales:
            row = lookup.get((topology["key"], system_key, scale))
            value = row.get(metric_spec["field"]) if row else None
            if value is None:
                continue
            if metric_spec["log"] and value <= 0:
                continue
            present_system_keys.append(system_key)
            break

    for system_key in PLOT_ORDER:
        if system_key not in present_system_keys:
            continue
        system = SYSTEM_BY_KEY[system_key]
        x_values = []
        y_values = []
        for scale in scales:
            row = lookup.get((topology["key"], system_key, scale))
            value = row.get(metric_spec["field"]) if row else None
            if value is None:
                continue
            if metric_spec["log"] and value <= 0:
                continue
            x_values.append(positions[scale])
            y_values.append(value)
        if not x_values:
            continue
        ax.plot(
            x_values,
            y_values,
            color=system["color"],
            marker=system["marker"],
            linewidth=2.2,
            markersize=6.5,
            markerfacecolor="none",
            markeredgecolor=system["color"],
            markeredgewidth=1.25,
            label=system["label"],
            zorder=SYSTEM_ZORDER.get(system_key, 3),
        )

    ax.set_xticks(range(len(scales)))
    ax.set_xticklabels(
        [f"{topology['label_prefix']}{scale}" for scale in scales],
        rotation=45,
        ha="right",
    )
    if scales:
        ax.set_xlim(-0.22, len(scales) - 1 + 0.22)
    ax.set_ylabel(metric_spec["ylabel"])
    if panel_label:
        ax.set_xlabel(panel_label, fontweight="bold")
    values = metric_values(rows, topology["key"], metric)
    apply_axis_style(ax, values, metric_spec["log"])


def legend_handles(system_keys=None):
    included = set(system_keys) if system_keys is not None else None
    return [
        Line2D(
            [0],
            [0],
            color=system["color"],
            marker=system["marker"],
            linewidth=2.5,
            markersize=8,
            markerfacecolor="none",
            markeredgecolor=system["color"],
            markeredgewidth=1.25,
            label=system["label"],
        )
        for system in SYSTEMS
        if included is None or str(system["key"]) in included
    ]


def save_figure(fig, out_dir, name, formats):
    written = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        written.append(path)
    plt.close(fig)
    return written


def topology_for_key(topology_key):
    for topology in TOPOLOGIES:
        if topology["key"] == topology_key:
            return topology
    raise SystemExit(f"unsupported topology: {topology_key}")


def filter_topology_rows(rows, topology_key):
    return [row for row in rows if row["topology"] == topology_key]


def filter_figure_rows(rows, spec):
    figure_rows = filter_topology_rows(rows, spec["topology"])
    max_scale = spec.get("max_scale")
    if max_scale is not None:
        figure_rows = [row for row in figure_rows if row["scale_value"] <= max_scale]
    return figure_rows


def plot_single_metric(rows, figure, out_dir, formats):
    spec = FIGURE_SPECS[figure]
    topology = topology_for_key(spec["topology"])
    metric = spec["metric"]
    figure_rows = filter_figure_rows(rows, spec)
    if not figure_rows:
        raise SystemExit(f"no rows found for {topology['key']}")

    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    plot_metric_axis(ax, figure_rows, topology, metric, panel_label=spec["xlabel"])
    metric_field = METRICS[metric]["field"]
    present_system_keys = [
        str(system["key"])
        for system in SYSTEMS
        if any(row["system_key"] == system["key"] and row.get(metric_field) is not None for row in figure_rows)
    ]
    ax.legend(
        handles=legend_handles(present_system_keys),
        loc="upper left",
        frameon=False,
        fontsize=8,
        handlelength=1.8,
    )
    fig.tight_layout()
    return figure_rows, save_figure(fig, out_dir, figure, formats)


def parse_formats(text):
    formats = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not formats:
        raise SystemExit("empty --formats")
    return formats


def load_rows_for_args(args, topology_keys):
    script_dir = Path(__file__).resolve().parent
    results_root = Path(args.results_root).resolve() if args.results_root else script_dir / "results"
    explicit = {
        "fattree": args.fattree_dir,
        "dragonfly": args.dragonfly_dir,
        "torus": args.torus_dir,
    }
    selected_topologies = [topology for topology in TOPOLOGIES if topology["key"] in topology_keys]
    stats_paths = {
        topology["key"]: resolve_stats_path(results_root, explicit[topology["key"]], topology)
        for topology in selected_topologies
    }

    rows = []
    for topology in selected_topologies:
        rows += load_topology_stats(topology, stats_paths[topology["key"]])
    if not rows:
        raise SystemExit("no supported rows found; expected RuleBased, NodeBfs/NodeBfsWithHost, or Global routing")
    return results_root, stats_paths, rows


def parser_for_figure(figure_label):
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", default=None, help="Directory containing latest/current result pointers.")
    parser.add_argument("--fattree-dir", default=None, help="Experiment 1 result directory or stats CSV.")
    parser.add_argument("--dragonfly-dir", default=None, help="Experiment 2 result directory or stats CSV.")
    parser.add_argument("--torus-dir", default=None, help="Experiment 3 result directory or stats CSV.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--formats", default="pdf,png")
    parser.description = f"Plot paper {figure_label}."
    return parser


def main_for_figure(figure):
    if figure not in FIGURE_SPECS:
        raise SystemExit(f"unsupported figure: {figure}")
    parser = parser_for_figure(figure)
    args = parser.parse_args()
    topology_key = FIGURE_SPECS[figure]["topology"]
    results_root, stats_paths, rows = load_rows_for_args(args, {topology_key})
    out_dir = Path(args.out_dir).resolve() if args.out_dir else results_root / "paper_figures" / figure
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)

    figure_rows, figure_paths = plot_single_metric(rows, figure, out_dir, formats)
    written = [write_normalized_stats(figure_rows, out_dir, FIGURE_SPECS[figure]["csv"])]
    written += figure_paths

    print(f"figures_dir={out_dir}")
    for key, path in stats_paths.items():
        print(f"{key}_stats={path}")
    for path in written:
        print(path)


if __name__ == "__main__":
    main_for_figure("figure8a")
