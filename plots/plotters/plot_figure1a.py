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


OUTPUT_BASENAME = "figure1a"
EXPERIMENT_STATS_NAME = "experiment_1.csv"
DEFAULT_ROUTING = "NodeBfs"
FIGSIZE = (3.85, 2.35)
LEGEND_FONTSIZE = 8.2
LABEL_FONTSIZE = 9.5
TICK_FONTSIZE = 8.0
LOWER_MAX_GB = 40.0
UPPER_MIN_GB = 100.0
BREAK_DISPLAY_GB = 14.0
UPPER_SCALE = 0.22
CSV_FIELDS = [
    "k",
    "fat_tree",
    "routing",
    "threads",
    "repeat_count",
    "initialization_peak_gb",
    "execution_increment_gb",
    "execution_peak_gb",
    "source",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
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


def mean(values: list[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
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
    if target.is_file():
        return target.resolve()
    stats_path = target / EXPERIMENT_STATS_NAME
    if stats_path.exists():
        return stats_path.resolve()
    return None


def resolve_source_path(
    results_root: Path,
    run_dir: str | None,
    stats_csv: str | None,
    input_csv: str | None,
) -> tuple[str, Path]:
    if input_csv:
        path = Path(input_csv).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"input CSV not found: {path}")
        return "stage", path

    if stats_csv:
        path = Path(stats_csv).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"stats CSV not found: {path}")
        return "stats", path

    if run_dir:
        path = Path(run_dir).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"run directory not found: {path}")
        if path.is_file():
            if path.name == f"{OUTPUT_BASENAME}_memory_stage.csv":
                return "stage", path
            return "stats", path
        for mode, candidate in (
            ("stats", path / EXPERIMENT_STATS_NAME),
            ("stage", path / f"{OUTPUT_BASENAME}_memory_stage.csv"),
            ("stage", path / "figures" / f"{OUTPUT_BASENAME}_memory_stage.csv"),
        ):
            if candidate.exists():
                return mode, candidate.resolve()
        raise SystemExit(
            f"cannot find {EXPERIMENT_STATS_NAME} or {OUTPUT_BASENAME}_memory_stage.csv under {path}"
        )

    for pointer_name in ("latest_fattree_ring_allreduce.txt", "current_experiment1_fattree_ring_allreduce.txt"):
        stats_path = resolve_pointer(results_root, pointer_name)
        if stats_path:
            return "stats", stats_path

    candidates = sorted(
        results_root.glob(f"experiment1_fattree_ring_allreduce_*/{EXPERIMENT_STATS_NAME}"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return "stats", candidates[0].resolve()
    raise SystemExit(f"cannot find FatTree Ring AllReduce stats under {results_root}")


def load_stage_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in read_csv(path):
        k = number(row.get("k"))
        init_peak = number(row.get("initialization_peak_gb"))
        exec_inc = number(row.get("execution_increment_gb"))
        exec_peak = number(row.get("execution_peak_gb"))
        if k is None or init_peak is None or exec_inc is None or exec_peak is None:
            continue
        rows.append(
            {
                "k": int(k),
                "fat_tree": row.get("fat_tree") or f"FT{int(k)}",
                "routing": row.get("routing") or DEFAULT_ROUTING,
                "threads": int(number(row.get("threads"), 1.0)),
                "repeat_count": int(number(row.get("repeat_count"), 1.0)),
                "initialization_peak_gb": f"{init_peak:.6f}",
                "execution_increment_gb": f"{exec_inc:.6f}",
                "execution_peak_gb": f"{exec_peak:.6f}",
                "source": row.get("source") or str(path),
            }
        )
    if not rows:
        raise SystemExit(f"no stage rows found in {path}")
    return sorted(rows, key=lambda row: int(row["k"]))


def load_stats_rows(path: Path, routing: str) -> list[dict[str, object]]:
    grouped: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(
        lambda: {
            "init_mem_gb": [],
            "exec_mem_gb": [],
            "repeat_count": [],
        }
    )

    for row in read_csv(path):
        if row.get("routing") != routing:
            continue
        k = number(row.get("scale_value") or row.get("k"))
        threads = number(row.get("threads"), 1.0)
        init_mem = number(row.get("init_mem_gb"))
        exec_mem = number(row.get("exec_mem_gb"))
        repeat_count = number(row.get("repeat_count"), 1.0)
        if k is None or threads is None or init_mem is None or exec_mem is None:
            continue
        bucket = grouped[(int(k), int(threads))]
        bucket["init_mem_gb"].append(init_mem)
        bucket["exec_mem_gb"].append(exec_mem)
        bucket["repeat_count"].append(repeat_count)

    rows: list[dict[str, object]] = []
    for (k, threads), values in sorted(grouped.items()):
        init_peak = mean(values["init_mem_gb"])
        exec_peak = mean(values["exec_mem_gb"])
        repeat_count = mean(values["repeat_count"])
        if init_peak is None or exec_peak is None:
            continue
        exec_increment = max(exec_peak - init_peak, 0.0)
        rows.append(
            {
                "k": k,
                "fat_tree": f"FT{k}",
                "routing": routing,
                "threads": threads,
                "repeat_count": int(round(repeat_count or len(values["init_mem_gb"]))),
                "initialization_peak_gb": f"{init_peak:.6f}",
                "execution_increment_gb": f"{exec_increment:.6f}",
                "execution_peak_gb": f"{exec_peak:.6f}",
                "source": str(path),
            }
        )

    if not rows:
        raise SystemExit(f"no rows for routing={routing} in {path}")
    return rows


def save_figure(fig, out_dir: Path, formats: list[str]) -> list[Path]:
    written: list[Path] = []
    for fmt in formats:
        path = out_dir / f"{OUTPUT_BASENAME}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03)
        written.append(path)
    plt.close(fig)
    return written


def y_display(value: float) -> float:
    if value <= LOWER_MAX_GB:
        return value
    if value < UPPER_MIN_GB:
        return LOWER_MAX_GB + BREAK_DISPLAY_GB
    return LOWER_MAX_GB + BREAK_DISPLAY_GB + (value - UPPER_MIN_GB) * UPPER_SCALE


def plot(rows: list[dict[str, object]], out_dir: Path, formats: list[str]) -> list[Path]:
    labels = [str(row["fat_tree"]) for row in rows]
    init_values = [float(row["initialization_peak_gb"]) for row in rows]
    exec_values = [float(row["execution_increment_gb"]) for row in rows]
    x = list(range(len(rows)))
    init_display = [y_display(value) for value in init_values]
    total_display = [y_display(init + inc) for init, inc in zip(init_values, exec_values)]
    exec_display = [max(total - init, 0.0) for init, total in zip(init_display, total_display)]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    width = 0.62
    ax.bar(
        x,
        init_display,
        width=width,
        color="#4C78A8",
        edgecolor="black",
        linewidth=0.5,
        label="initialization peak",
        zorder=3,
    )
    ax.bar(
        x,
        exec_display,
        width=width,
        bottom=init_display,
        color="#F58518",
        edgecolor="black",
        linewidth=0.5,
        hatch="////",
        label="Execution increment",
        zorder=3,
    )
    for idx, (init_value, exec_value) in enumerate(zip(init_values, exec_values)):
        total = init_value + exec_value
        if total <= LOWER_MAX_GB:
            continue
        ax.bar(
            idx,
            y_display(UPPER_MIN_GB) - y_display(LOWER_MAX_GB),
            width=width,
            bottom=y_display(LOWER_MAX_GB),
            color="white",
            edgecolor="black",
            linewidth=0.35,
            hatch="....",
            zorder=5,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=TICK_FONTSIZE)
    ax.set_xlabel("Fat-tree scale (k)", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("Memory footprint (GB)", fontsize=LABEL_FONTSIZE)
    ymax = max((a + b for a, b in zip(init_values, exec_values)), default=1.0)
    ax.set_ylim(0, y_display(max(540.0, ymax * 1.05)))
    ticks = [0, 20, 40, 100, 300, 500]
    ax.set_yticks([y_display(float(tick)) for tick in ticks])
    ax.set_yticklabels([str(tick) for tick in ticks], fontsize=TICK_FONTSIZE)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="--", alpha=0.45, zorder=0)
    ax.tick_params(direction="in", top=True, right=True)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)
    ymin, ymax_display = ax.get_ylim()
    break_y = (y_display(LOWER_MAX_GB) + y_display(UPPER_MIN_GB)) / 2.0
    break_y_frac = (break_y - ymin) / (ymax_display - ymin)
    for xpos in (-0.015, 1.015):
        ax.plot(
            [xpos - 0.012, xpos + 0.012],
            [break_y_frac - 0.01, break_y_frac + 0.01],
            transform=ax.transAxes,
            color="black",
            linewidth=0.8,
            clip_on=False,
        )
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.legend(
        handles,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        ncol=2,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        columnspacing=0.9,
        handlelength=1.2,
    )
    return save_figure(fig, out_dir, formats)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", default=str(Path(__file__).resolve().parent / "results"))
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--stats-csv", default=None)
    parser.add_argument("--input-csv", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--routing", default=DEFAULT_ROUTING)
    parser.add_argument("--formats", default="pdf,png")
    args = parser.parse_args()

    results_root = Path(args.results_root).expanduser().resolve()
    mode, source_path = resolve_source_path(results_root, args.run_dir, args.stats_csv, args.input_csv)
    if args.out_dir:
        out_dir = Path(args.out_dir).expanduser().resolve()
    elif mode == "stage":
        out_dir = source_path.parent / "figure1a"
    else:
        out_dir = source_path.parent / "figures" / "figure1a"
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)

    if mode == "stage":
        rows = load_stage_rows(source_path)
    else:
        rows = load_stats_rows(source_path, args.routing)

    stats_path = out_dir / f"{OUTPUT_BASENAME}_memory_stage.csv"
    write_csv(stats_path, rows)
    written = [stats_path] + plot(rows, out_dir, formats)

    print(f"figures_dir={out_dir}")
    print(f"source_csv={source_path}")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
