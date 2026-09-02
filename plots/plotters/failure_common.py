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


SYSTEMS = [
    {
        "key": "nvwa",
        "label": "Nvwa",
        "routings": {"RuleBased"},
        "color": "#1f77b4",
        "marker": "^",
    },
    {
        "key": "bfs",
        "label": "BFS",
        "routings": {"NodeBfs", "NodeBfsStrict", "NodeBfsWithHost"},
        "color": "#ff7f0e",
        "marker": "s",
    },
]

SYSTEM_BY_KEY = {str(system["key"]): system for system in SYSTEMS}
PLOT_ORDER = ["bfs", "nvwa"]
SYSTEM_ZORDER = {"bfs": 4, "nvwa": 5}

CSV_FIELDS = [
    "failure_rate",
    "k",
    "fat_tree",
    "system",
    "routing",
    "exec_time_s",
    "exec_peak_mem_gb",
    "wall_s",
    "source",
]


FIGURE_SPECS = {
    "figure13a": {
        "metric": "exec_time_s",
        "ylabel": "Execution time (s)",
        "xlabel": "(a) Execution time",
        "csv": "figure13a_failure_execution_time.csv",
    },
    "figure13b": {
        "metric": "exec_peak_mem_gb",
        "ylabel": "Peak memory (GB)",
        "xlabel": "(b) Peak memory",
        "csv": "figure13b_failure_memory.csv",
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


def system_for_routing(routing: str) -> dict[str, object] | None:
    for system in SYSTEMS:
        if routing in system["routings"]:
            return system
    return None


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
    candidate = path / "experiment_8.csv"
    if candidate.exists():
        return candidate.resolve()
    return None


def resolve_stats_path(results_root: Path, explicit_run_dir: str | None, explicit_stats_csv: str | None) -> Path:
    if explicit_stats_csv:
        path = Path(explicit_stats_csv).expanduser()
        if path.is_dir():
            path = path / "experiment_8.csv"
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
        raise SystemExit(f"cannot find experiment_8.csv under {path}")

    for pointer_name in (
        "latest_fattree_failure_handling.txt",
        "current_experiment9_fattree_failure_handling.txt",
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
        results_root.glob("experiment9_fattree_failure_handling_*/experiment_8.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0].resolve()
    raise SystemExit(f"cannot find experiment9 failure results under {results_root}")


def choose_failure_rate(rows: list[dict[str, str]], requested: str | None) -> float:
    rates = sorted({rate for row in rows if (rate := number(row.get("failure_rate"))) is not None})
    if not rates:
        raise SystemExit("no failure_rate values found")
    if requested is not None:
        wanted = number(requested)
        if wanted is None:
            raise SystemExit(f"invalid failure rate: {requested}")
        for rate in rates:
            if math.isclose(rate, wanted, rel_tol=1e-9, abs_tol=1e-12):
                return rate
        raise SystemExit(f"failure rate {requested} not found; available: {', '.join(str(rate) for rate in rates)}")
    if len(rates) > 1:
        print(f"[info] multiple failure rates found; plotting {rates[0]:g}. Set FAILURE_RATE to override.")
    return rates[0]


def load_rows(path: Path, *, failure_rate: float, include_failed: bool) -> list[dict[str, object]]:
    buckets: dict[tuple[int, str], dict[str, object]] = defaultdict(
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
        row_rate = number(row.get("failure_rate"))
        if row_rate is None or not math.isclose(row_rate, failure_rate, rel_tol=1e-9, abs_tol=1e-12):
            continue
        routing = row.get("routing", "")
        system = system_for_routing(routing)
        k = number(row.get("k"))
        exec_time = number(row.get("exec_s"))
        exec_mem = number(row.get("exec_peak_mem_gb"))
        wall = number(row.get("wall_s"))
        if system is None or k is None or exec_time is None or exec_mem is None:
            continue
        key = (int(k), str(system["key"]))
        bucket = buckets[key]
        bucket["routing"].add(routing)
        bucket["exec_time_s"].append(exec_time)
        bucket["exec_peak_mem_gb"].append(exec_mem)
        bucket["wall_s"].append(wall)

    rows: list[dict[str, object]] = []
    for (k, system_key), values in sorted(buckets.items()):
        system = next(item for item in SYSTEMS if item["key"] == system_key)
        exec_time = mean(values["exec_time_s"])
        exec_mem = mean(values["exec_peak_mem_gb"])
        wall = mean(values["wall_s"])
        if exec_time is None or exec_mem is None:
            continue
        rows.append(
            {
                "failure_rate": failure_rate,
                "k": k,
                "fat_tree": f"FT{k}",
                "system_key": system_key,
                "system": system["label"],
                "routing": ",".join(sorted(values["routing"])),
                "exec_time_s": exec_time,
                "exec_peak_mem_gb": exec_mem,
                "wall_s": wall,
                "source": str(path),
            }
        )

    if not rows:
        raise SystemExit(f"no successful RuleBased/NodeBfs rows found in {path} for failure_rate={failure_rate:g}")
    return rows


def save_figure(fig, out_dir: Path, name: str, formats: list[str]) -> list[Path]:
    written = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        written.append(path)
    plt.close(fig)
    return written


def apply_axis_style(ax, values: list[float]) -> None:
    ax.grid(True, which="major", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    if values:
        top = max(values)
        ax.set_ylim(bottom=0.0, top=top * 1.14 if top > 0 else 1.0)


def legend_handles(system_keys: list[str] | None = None) -> list[Line2D]:
    included = set(system_keys) if system_keys is not None else None
    return [
        Line2D(
            [0],
            [0],
            color=str(system["color"]),
            marker=str(system["marker"]),
            linewidth=2.2,
            markersize=6.5,
            markerfacecolor="none",
            markeredgecolor=str(system["color"]),
            markeredgewidth=1.25,
            label=str(system["label"]),
        )
        for system in SYSTEMS
        if included is None or str(system["key"]) in included
    ]


def plot_metric_axis(
    ax,
    rows: list[dict[str, object]],
    *,
    metric: str,
    ylabel: str,
    xlabel: str | None = None,
) -> None:
    k_values = sorted({int(row["k"]) for row in rows})
    positions = {k: idx for idx, k in enumerate(k_values)}
    values: list[float] = []
    present_system_keys = []

    for system in SYSTEMS:
        system_key = str(system["key"])
        for k in k_values:
            matches = [
                row
                for row in rows
                if row["system_key"] == system_key and int(row["k"]) == k and row.get(metric) is not None
            ]
            value = mean([float(row[metric]) for row in matches])
            if value is not None:
                present_system_keys.append(system_key)
                break

    for system_key in PLOT_ORDER:
        if system_key not in present_system_keys:
            continue
        system = SYSTEM_BY_KEY[system_key]
        x_values = []
        y_values = []
        for k in k_values:
            matches = [
                row
                for row in rows
                if row["system_key"] == system_key and int(row["k"]) == k and row.get(metric) is not None
            ]
            value = mean([float(row[metric]) for row in matches])
            if value is None:
                continue
            x_values.append(positions[k])
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
            markerfacecolor="none",
            markeredgecolor=str(system["color"]),
            markeredgewidth=1.25,
            label=str(system["label"]),
            zorder=SYSTEM_ZORDER.get(system_key, 3),
        )

    ax.set_xticks(range(len(k_values)))
    ax.set_xticklabels([f"FT{k}" for k in k_values], rotation=35, ha="right")
    if k_values:
        ax.set_xlim(-0.2, len(k_values) - 1 + 0.2)
    ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel, fontweight="bold")
    apply_axis_style(ax, values)


def plot_single_metric(rows: list[dict[str, object]], figure: str, out_dir: Path, formats: list[str]) -> list[Path]:
    spec = FIGURE_SPECS[figure]
    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    plot_metric_axis(
        ax,
        rows,
        metric=str(spec["metric"]),
        ylabel=str(spec["ylabel"]),
        xlabel=str(spec["xlabel"]),
    )
    metric = str(spec["metric"])
    present_system_keys = [
        str(system["key"])
        for system in SYSTEMS
        if any(row["system_key"] == system["key"] and row.get(metric) is not None for row in rows)
    ]
    ax.legend(handles=legend_handles(present_system_keys), loc="upper left", frameon=False, fontsize=8, handlelength=1.8)
    fig.tight_layout()
    return save_figure(fig, out_dir, figure, formats)


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
    parser.add_argument("--failure-rate", default=None)
    parser.add_argument("--include-failed", action="store_true")
    args = parser.parse_args()

    results_root = Path(args.results_root).expanduser().resolve()
    stats_path = resolve_stats_path(results_root, args.run_dir, args.stats_csv)
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else stats_path.parent / "figures" / figure
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)

    raw_rows = read_csv(stats_path)
    failure_rate = choose_failure_rate(raw_rows, args.failure_rate)
    rows = load_rows(stats_path, failure_rate=failure_rate, include_failed=args.include_failed)

    stats_out = out_dir / str(FIGURE_SPECS[figure]["csv"])
    write_csv(stats_out, rows)
    written = [stats_out] + plot_single_metric(rows, figure, out_dir, formats)

    print(f"figures_dir={out_dir}")
    print(f"failure_stats={stats_path}")
    print(f"failure_rate={failure_rate:g}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_for_figure("figure13a"))
