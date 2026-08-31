#!/usr/bin/env python3
from __future__ import annotations

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


PANELS = [
    {
        "topology": "dragonfly",
        "scale_name": "h",
        "scale_value": 4,
        "scale_label": "DF4",
        "caption": "(a) DF4",
        "stats_name": "experiment_7_dragonfly.csv",
        "figure_name": "exec_dragonfly_h4",
        "data_sizes": [1048576, 8388608, 16777216, 67108864, 134217728],
    },
    {
        "topology": "dragonfly",
        "scale_name": "h",
        "scale_value": 6,
        "scale_label": "DF6",
        "caption": "(b) DF6",
        "stats_name": "experiment_7_dragonfly.csv",
        "figure_name": "exec_dragonfly_h6",
        "data_sizes": [1048576, 8388608, 16777216],
    },
    {
        "topology": "fattree",
        "scale_name": "k",
        "scale_value": 16,
        "scale_label": "FT16",
        "caption": "(c) FT16",
        "stats_name": "experiment_7_fattree.csv",
        "figure_name": "exec_fattree_k16",
        "data_sizes": [1048576, 8388608, 16777216, 67108864, 134217728],
    },
    {
        "topology": "fattree",
        "scale_name": "k",
        "scale_value": 24,
        "scale_label": "FT24",
        "caption": "(d) FT24",
        "stats_name": "experiment_7_fattree.csv",
        "figure_name": "exec_fattree_k24",
        "data_sizes": [1048576, 8388608, 16777216, 67108864, 134217728],
    },
]


FIGURE_SPECS = {
    "figure11a": {"panel": PANELS[0], "csv": "figure11a_workload_size_dragonfly_h4.csv"},
    "figure11b": {"panel": PANELS[1], "csv": "figure11b_workload_size_dragonfly_h6.csv"},
    "figure11c": {"panel": PANELS[2], "csv": "figure11c_workload_size_fattree_k16.csv"},
    "figure11d": {"panel": PANELS[3], "csv": "figure11d_workload_size_fattree_k24.csv"},
}


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
]


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


def number(value: str | None, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(clean) if clean else None


def system_for_routing(routing: str) -> dict[str, object] | None:
    for system in SYSTEMS:
        if routing in system["routings"]:
            return system
    return None


def resolve_run_dir(results_root: Path, explicit_run_dir: str | None) -> Path:
    if explicit_run_dir:
        path = Path(explicit_run_dir).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"run directory not found: {path}")
        return path

    for pointer_name in (
        "latest_workload_size_allreduce.txt",
        "current_experiment8_workload_size_allreduce.txt",
    ):
        pointer = results_root / pointer_name
        if not pointer.exists():
            continue
        target_text = pointer.read_text(encoding="utf-8").strip()
        if not target_text:
            continue
        target = Path(target_text).expanduser()
        if not target.is_absolute():
            target = (pointer.parent / target).resolve()
        if target.exists():
            return target.resolve()

    candidates = sorted(
        results_root.glob("experiment8_workload_size_allreduce_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0].resolve()
    raise SystemExit(f"cannot find experiment8_workload_size_allreduce results under {results_root}")


def stats_paths(run_dir: Path) -> dict[str, Path]:
    candidates = {
        "dragonfly": [
            run_dir / "experiment_7_dragonfly.csv",
            run_dir / "dragonfly" / "experiment_7_dragonfly.csv",
        ],
        "fattree": [
            run_dir / "experiment_7_fattree.csv",
            run_dir / "fattree" / "experiment_7_fattree.csv",
        ],
    }
    paths = {
        topology: next((path for path in possible_paths if path.exists()), possible_paths[0])
        for topology, possible_paths in candidates.items()
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise SystemExit("missing stats file(s): " + ", ".join(missing))
    return paths


def data_size_label(data_size: int) -> str:
    mib = 1024 * 1024
    if data_size % mib == 0:
        return f"{data_size // mib}MB"
    return f"{data_size}B"


def load_rows(paths: dict[str, Path]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, int, str, int], dict[str, object]] = {}
    for topology, path in paths.items():
        for row in read_csv(path):
            routing = row.get("routing", "")
            system = system_for_routing(routing)
            if system is None:
                continue
            scale = number(row.get("scale_value"))
            data_size = number(row.get("data_size"))
            exec_time = number(row.get("exec_time_s"))
            if scale is None or data_size is None or exec_time is None:
                continue
            scale_i = int(scale)
            data_size_i = int(data_size)
            key = (topology, scale_i, str(system["key"]), data_size_i)
            entry = buckets.setdefault(
                key,
                {
                    "topology": topology,
                    "scale_value": scale_i,
                    "system_key": system["key"],
                    "system": system["label"],
                    "routing": set(),
                    "data_size": data_size_i,
                    "exec_time_s": [],
                    "source": str(path),
                },
            )
            entry["routing"].add(routing)
            entry["exec_time_s"].append(exec_time)

    rows = []
    for (_topology, _scale, _system, _data_size), entry in sorted(buckets.items()):
        exec_time = mean(entry["exec_time_s"])
        if exec_time is None:
            continue
        rows.append(
            {
                "topology": entry["topology"],
                "scale_value": entry["scale_value"],
                "scale_label": scale_label(str(entry["topology"]), int(entry["scale_value"])),
                "system_key": entry["system_key"],
                "system": entry["system"],
                "routing": ",".join(sorted(entry["routing"])),
                "data_size": entry["data_size"],
                "data_size_label": data_size_label(int(entry["data_size"])),
                "exec_time_s": exec_time,
                "source": entry["source"],
            }
        )
    return rows


def scale_label(topology: str, scale: int) -> str:
    if topology == "dragonfly":
        return f"DF{scale}"
    if topology == "fattree":
        return f"FT{scale}"
    return str(scale)


def write_normalized_stats(rows: list[dict[str, object]], out_dir: Path, name: str) -> Path:
    fields = [
        "topology",
        "scale_value",
        "scale_label",
        "data_size",
        "data_size_label",
        "system",
        "routing",
        "exec_time_s",
        "source",
    ]
    formatted = []
    for row in rows:
        formatted.append(
            {
                "topology": str(row["topology"]),
                "scale_value": str(row["scale_value"]),
                "scale_label": str(row["scale_label"]),
                "data_size": str(row["data_size"]),
                "data_size_label": str(row["data_size_label"]),
                "system": str(row["system"]),
                "routing": str(row["routing"]),
                "exec_time_s": f"{float(row['exec_time_s']):.6f}",
                "source": str(row["source"]),
            }
        )
    path = out_dir / name
    write_csv(path, fields, formatted)
    return path


def panel_rows(rows: list[dict[str, object]], panel: dict[str, object]) -> list[dict[str, object]]:
    data_sizes = {int(value) for value in panel.get("data_sizes", [])}
    return [
        row
        for row in rows
        if row["topology"] == panel["topology"] and int(row["scale_value"]) == int(panel["scale_value"])
        and (not data_sizes or int(row["data_size"]) in data_sizes)
    ]


def apply_axis_style(ax, values: list[float]) -> None:
    ax.grid(True, which="major", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    if values:
        top = max(values)
        ax.set_ylim(bottom=0.0, top=top * 1.12 if top > 0 else 1.0)


def legend_handles() -> list[Line2D]:
    return [
        Line2D(
            [0],
            [0],
            color=str(system["color"]),
            marker=str(system["marker"]),
            linewidth=2.5,
            markersize=8,
            label=str(system["label"]),
        )
        for system in SYSTEMS
    ]


def plot_panel_axis(ax, rows: list[dict[str, object]], panel: dict[str, object], *, xlabel: str | None = None) -> None:
    subset = panel_rows(rows, panel)
    sizes = sorted({int(row["data_size"]) for row in subset})
    positions = {size: idx for idx, size in enumerate(sizes)}
    values: list[float] = []

    for system in SYSTEMS:
        x_values = []
        y_values = []
        for size in sizes:
            matches = [
                row
                for row in subset
                if row["system_key"] == system["key"] and int(row["data_size"]) == size
            ]
            if not matches:
                continue
            value = mean([float(row["exec_time_s"]) for row in matches])
            if value is None:
                continue
            x_values.append(positions[size])
            y_values.append(value)
            values.append(value)
        if not x_values:
            continue
        ax.plot(
            x_values,
            y_values,
            color=str(system["color"]),
            marker=str(system["marker"]),
            linewidth=2.2,
            markersize=6.5,
            label=str(system["label"]),
        )

    ax.set_xticks(range(len(sizes)))
    ax.set_xticklabels([data_size_label(size) for size in sizes], rotation=45, ha="right")
    ax.set_ylabel("Execution time (s)")
    if xlabel:
        ax.set_xlabel(xlabel, fontweight="bold")
    apply_axis_style(ax, values)


def save_figure(fig, out_dir: Path, name: str, formats: list[str]) -> list[Path]:
    written = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        written.append(path)
    plt.close(fig)
    return written


def plot_single_panel(
    rows: list[dict[str, object]],
    figure: str,
    out_dir: Path,
    formats: list[str],
) -> tuple[list[dict[str, object]], list[Path]]:
    spec = FIGURE_SPECS[figure]
    panel = spec["panel"]
    subset = panel_rows(rows, panel)
    if not subset:
        raise SystemExit(f"no rows found for {panel['scale_label']}")

    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    plot_panel_axis(ax, rows, panel, xlabel=str(panel["caption"]))
    ax.legend(loc="upper left", frameon=False, fontsize=8, handlelength=1.8)
    fig.tight_layout()
    return subset, save_figure(fig, out_dir, figure, formats)


def parse_formats(text: str) -> list[str]:
    formats = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not formats:
        raise SystemExit("empty --formats")
    return formats


def main_for_figure(figure: str) -> int:
    if figure not in FIGURE_SPECS:
        raise SystemExit(f"unsupported figure: {figure}")
    parser = argparse.ArgumentParser()
    parser.description = f"Plot paper {figure}."
    parser.add_argument("--results-root", default=None, help="Directory containing latest/current result pointers.")
    parser.add_argument("--run-dir", default=None, help="Experiment 8 result directory.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--formats", default="pdf,png")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    results_root = Path(args.results_root).resolve() if args.results_root else script_dir / "results"
    run_dir = resolve_run_dir(results_root, args.run_dir)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir / "figures" / figure
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)

    paths = stats_paths(run_dir)
    rows = load_rows(paths)
    if not rows:
        raise SystemExit("no supported rows found; expected RuleBased or NodeBfs rows with data_size")

    figure_rows, figure_paths = plot_single_panel(rows, figure, out_dir, formats)
    written = [write_normalized_stats(figure_rows, out_dir, FIGURE_SPECS[figure]["csv"])]
    written += figure_paths

    print(f"figures_dir={out_dir}")
    print(f"run_dir={run_dir}")
    for topology, path in paths.items():
        print(f"{topology}_stats={path}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_for_figure("figure11a"))
