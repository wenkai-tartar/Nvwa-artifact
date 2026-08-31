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


SERIES = {
    "baseline": {"label": "Shortest", "color": "#1f77b4", "marker": "o"},
    "valiant": {"label": "Valiant", "color": "#ff7f0e", "marker": "s"},
    "ugal": {"label": "UGAL", "color": "#2ca02c", "marker": "^"},
    "detour1": {"label": "Detour1", "color": "#ff7f0e", "marker": "s"},
    "detour2": {"label": "Detour2", "color": "#d62728", "marker": "D"},
}

PLATFORMS = {
    "dragonfly": {
        "param_name": "h",
        "xlabel": "Dragonfly h",
        "xprefix": "DF",
        "series": ["baseline", "valiant", "ugal"],
    },
    "torus": {
        "param_name": "d",
        "xlabel": "3D-Torus d",
        "xprefix": "TR",
        "series": ["baseline", "detour1", "detour2"],
    },
}

CSV_FIELDS = [
    "platform",
    "param_name",
    "param_value",
    "scale_label",
    "series",
    "routing",
    "exec_time_s",
    "exec_peak_mem_gb",
    "wall_s",
    "source",
]


FIGURE_SPECS = {
    "figure14a": {
        "platform": "dragonfly",
        "metric": "exec_time_s",
        "ylabel": "Execution time (s)",
        "xlabel": "(a) DF time",
        "csv": "figure14a_nonminimal_dragonfly_time.csv",
        "yscale": "log",
    },
    "figure14b": {
        "platform": "dragonfly",
        "metric": "exec_peak_mem_gb",
        "ylabel": "Peak memory (GB)",
        "xlabel": "(b) DF memory",
        "csv": "figure14b_nonminimal_dragonfly_memory.csv",
    },
    "figure14c": {
        "platform": "torus",
        "metric": "exec_time_s",
        "ylabel": "Execution time (s)",
        "xlabel": "(c) TR time",
        "csv": "figure14c_nonminimal_torus_time.csv",
        "yscale": "log",
    },
    "figure14d": {
        "platform": "torus",
        "metric": "exec_peak_mem_gb",
        "ylabel": "Peak memory (GB)",
        "xlabel": "(d) TR memory",
        "csv": "figure14d_nonminimal_torus_memory.csv",
    },
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: format_cell(row.get(field)) for field in CSV_FIELDS})


def format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


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


def parse_formats(text: str) -> list[str]:
    formats = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not formats:
        raise SystemExit("empty --formats")
    return formats


def resolve_pointer(results_root: Path, pointer_name: str) -> Path | None:
    pointer = results_root / pointer_name
    if not pointer.exists():
        return None
    target_text = pointer.read_text(encoding="utf-8").strip()
    if not target_text:
        return None
    target = Path(target_text).expanduser()
    if not target.is_absolute():
        target = (pointer.parent / target).resolve()
    return target.resolve()


def stats_from_run_dir(path: Path) -> Path | None:
    candidate = path / "experiment_9.csv"
    if candidate.exists():
        return candidate.resolve()
    return None


def resolve_stats_path(results_root: Path, explicit_run_dir: str | None, explicit_stats_csv: str | None) -> Path:
    if explicit_stats_csv:
        path = Path(explicit_stats_csv).expanduser()
        if path.is_dir():
            path = path / "experiment_9.csv"
        path = path.resolve()
        if not path.exists():
            raise SystemExit(f"stats CSV not found: {path}")
        return path

    if explicit_run_dir:
        path = Path(explicit_run_dir).expanduser().resolve()
        if path.is_file():
            return path
        candidate = stats_from_run_dir(path)
        if candidate:
            return candidate
        raise SystemExit(f"cannot find experiment_9.csv under {path}")

    for pointer_name in (
        "latest_nonminimal_routing.txt",
        "current_experiment10_nonminimal_routing.txt",
    ):
        target = resolve_pointer(results_root, pointer_name)
        if not target:
            continue
        if target.is_file():
            return target
        candidate = stats_from_run_dir(target)
        if candidate:
            return candidate

    candidates = sorted(
        results_root.glob("experiment10_nonminimal_routing_*/experiment_9.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0].resolve()
    raise SystemExit(f"cannot find experiment10 non-minimal results under {results_root}")


def platform_for_group(group: str) -> str | None:
    if group.startswith("dragonfly_"):
        return "dragonfly"
    if group.startswith("torus_"):
        return "torus"
    return None


def series_for_row(group: str, variant: str) -> str | None:
    if variant == "baseline":
        return "baseline"
    if group == "dragonfly_valiant":
        return "valiant"
    if group == "dragonfly_ugal":
        return "ugal"
    if group == "torus_detour1":
        return "detour1"
    if group == "torus_detour2":
        return "detour2"
    return None


def load_rows(path: Path, *, include_failed: bool) -> list[dict[str, object]]:
    buckets: dict[tuple[str, int, str], dict[str, object]] = defaultdict(
        lambda: {
            "routing": set(),
            "exec_time_s": [],
            "exec_peak_mem_gb": [],
            "wall_s": [],
        }
    )

    for row in read_csv(path):
        rc = number(row.get("rc"))
        if not include_failed and rc != 0:
            continue
        group = row.get("group", "")
        variant = row.get("variant", "")
        platform = platform_for_group(group)
        series = series_for_row(group, variant)
        param = number(row.get("param_value"))
        exec_time = number(row.get("exec_s"))
        exec_mem = number(row.get("exec_peak_mem_gb"))
        wall = number(row.get("wall_s"))
        if platform is None or series is None or param is None or exec_time is None or exec_mem is None:
            continue
        key = (platform, int(param), series)
        bucket = buckets[key]
        bucket["routing"].add(row.get("routing", ""))
        bucket["exec_time_s"].append(exec_time)
        bucket["exec_peak_mem_gb"].append(exec_mem)
        bucket["wall_s"].append(wall)

    rows: list[dict[str, object]] = []
    for (platform, param_value, series), values in sorted(buckets.items()):
        exec_time = mean(values["exec_time_s"])
        exec_mem = mean(values["exec_peak_mem_gb"])
        wall = mean(values["wall_s"])
        if exec_time is None or exec_mem is None:
            continue
        platform_spec = PLATFORMS[platform]
        rows.append(
            {
                "platform": platform,
                "param_name": platform_spec["param_name"],
                "param_value": param_value,
                "scale_label": f"{platform_spec['xprefix']}{param_value}",
                "series_key": series,
                "series": SERIES[series]["label"],
                "routing": ",".join(sorted(item for item in values["routing"] if item)),
                "exec_time_s": exec_time,
                "exec_peak_mem_gb": exec_mem,
                "wall_s": wall,
                "source": str(path),
            }
        )

    if not rows:
        raise SystemExit(f"no successful non-minimal rows found in {path}")
    return rows


def save_figure(fig, out_dir: Path, name: str, formats: list[str]) -> list[Path]:
    written = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        written.append(path)
    plt.close(fig)
    return written


def apply_axis_style(ax, values: list[float], *, yscale: str = "linear") -> None:
    ax.grid(True, which="major", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    if values:
        if yscale == "log":
            clean = [value for value in values if value > 0 and math.isfinite(value)]
            if clean:
                ax.set_yscale("log")
                ax.set_ylim(bottom=min(clean) / 1.2, top=max(clean) * 1.2)
        else:
            top = max(values)
            ax.set_ylim(bottom=0.0, top=top * 1.14 if top > 0 else 1.0)


def legend_handles(platform: str) -> list[Line2D]:
    return [
        Line2D(
            [0],
            [0],
            color=str(SERIES[series]["color"]),
            marker=str(SERIES[series]["marker"]),
            linewidth=2.2,
            markersize=6.5,
            label=str(SERIES[series]["label"]),
        )
        for series in PLATFORMS[platform]["series"]
    ]


def plot_metric_axis(
    ax,
    rows: list[dict[str, object]],
    *,
    platform: str,
    metric: str,
    ylabel: str,
    xlabel: str | None = None,
    yscale: str = "linear",
) -> None:
    subset = [row for row in rows if row["platform"] == platform]
    platform_spec = PLATFORMS[platform]
    params = sorted({int(row["param_value"]) for row in subset})
    positions = {value: idx for idx, value in enumerate(params)}
    values: list[float] = []

    for series in platform_spec["series"]:
        x_values = []
        y_values = []
        for param in params:
            matches = [
                row
                for row in subset
                if row["series_key"] == series and int(row["param_value"]) == param and row.get(metric) is not None
            ]
            value = mean([float(row[metric]) for row in matches])
            if value is None:
                continue
            x_values.append(positions[param])
            y_values.append(value)
            values.append(value)
        if not x_values:
            continue
        ax.plot(
            x_values,
            y_values,
            color=str(SERIES[series]["color"]),
            marker=str(SERIES[series]["marker"]),
            linewidth=2.2,
            markersize=6.5,
            label=str(SERIES[series]["label"]),
        )

    ax.set_xticks(range(len(params)))
    ax.set_xticklabels([f"{platform_spec['xprefix']}{value}" for value in params], rotation=35, ha="right")
    ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel, fontweight="bold")
    apply_axis_style(ax, values, yscale=yscale)


def plot_single_metric(
    rows: list[dict[str, object]],
    figure: str,
    out_dir: Path,
    formats: list[str],
) -> tuple[list[dict[str, object]], list[Path]]:
    spec = FIGURE_SPECS[figure]
    platform = str(spec["platform"])
    figure_rows = [row for row in rows if row["platform"] == platform]
    if not figure_rows:
        raise SystemExit(f"no rows found for {platform}")

    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    plot_metric_axis(
        ax,
        figure_rows,
        platform=platform,
        metric=str(spec["metric"]),
        ylabel=str(spec["ylabel"]),
        xlabel=str(spec["xlabel"]),
        yscale=str(spec.get("yscale", "linear")),
    )
    ax.legend(handles=legend_handles(platform), loc="upper left", frameon=False, fontsize=8, handlelength=1.8)
    fig.tight_layout()
    return figure_rows, save_figure(fig, out_dir, figure, formats)


def main_for_figure(figure: str) -> int:
    if figure not in FIGURE_SPECS:
        raise SystemExit(f"unsupported figure: {figure}")
    parser = argparse.ArgumentParser()
    parser.description = f"Plot paper {figure}."
    parser.add_argument("--results-root", default=str(Path(__file__).resolve().parent / "results"))
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--stats-csv", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--formats", default="pdf,png")
    parser.add_argument("--include-failed", action="store_true")
    args = parser.parse_args()

    results_root = Path(args.results_root).expanduser().resolve()
    stats_path = resolve_stats_path(results_root, args.run_dir, args.stats_csv)
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else stats_path.parent / "figures" / figure
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)

    rows = load_rows(stats_path, include_failed=args.include_failed)
    figure_rows, figure_paths = plot_single_metric(rows, figure, out_dir, formats)
    stats_out = out_dir / str(FIGURE_SPECS[figure]["csv"])
    write_csv(stats_out, figure_rows)
    written = [stats_out] + figure_paths

    print(f"figures_dir={out_dir}")
    print(f"nonminimal_stats={stats_path}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_for_figure("figure14a"))
