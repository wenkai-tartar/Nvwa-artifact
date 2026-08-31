#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "nvwa-ae-matplotlib"))

import matplotlib

from plot_style import configure_matplotlib

configure_matplotlib(matplotlib)
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, LogFormatterMathtext, MultipleLocator
from matplotlib.patches import Patch

ROUTING_ORDER = {
    "RuleBased": 0,
    "NodeBfs": 1,
    "NodeBfsWithHost": 2,
    "Global": 3,
}

ROUTING_STYLES = {
    "RuleBased": {"label": "Nüwa", "color": "#4C78A8"},
    "NodeBfs": {"label": "ns-3-dc", "color": "#F58518"},
    "NodeBfsWithHost": {"label": "ns-3-dc", "color": "#E45756"},
    "Global": {"label": "Global", "color": "#54A24B"},
}

DEFAULT_COLOR = "#72B7B2"
BAR_COLORS = {
    "initialization": "#4C78A8",
    "execution": "#F58518",
}
PANEL_FIGSIZE = (3.35, 2.35)
LABEL_FONTSIZE = 11.0
TICK_FONTSIZE = 10.0
LEGEND_FONTSIZE = 10.0
ANNOTATION_FONTSIZE = 9.0
DEFAULT_SUMMARY_NAME = "experiment_6.csv"


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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


def integer(value, default=None):
    parsed = number(value, default=None)
    if parsed is None:
        return default
    return int(parsed)


def gb_from_kb(value):
    parsed = number(value)
    if parsed is None:
        return None
    return parsed / (1024.0 * 1024.0)


def parse_formats(text):
    formats = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not formats:
        raise SystemExit("empty --formats")
    return formats


def resolve_pointer(results_root, pointer_name, summary_name):
    pointer = results_root / pointer_name
    if not pointer.exists():
        return None
    target_text = pointer.read_text(encoding="utf-8").strip()
    if not target_text:
        return None
    target = Path(target_text).expanduser()
    if not target.is_absolute():
        target = (pointer.parent / target).resolve()
    if target.is_file() and target.name == summary_name:
        target = target.parent
    return target.resolve()


def resolve_experiment_dir(results_root, explicit_dir, summary_name):
    if explicit_dir:
        path = Path(explicit_dir).expanduser().resolve()
        if path.is_file() and path.name == summary_name:
            path = path.parent
        if not (path / summary_name).exists():
            raise SystemExit(f"ATLAHS summary CSV not found under {path}: {summary_name}")
        return path

    for pointer_name in (
        "latest_atlahs_dragonfly_production_workload.txt",
        "current_experiment6_atlahs_dragonfly_production_workload.txt",
    ):
        target = resolve_pointer(results_root, pointer_name, summary_name)
        if target and (target / summary_name).exists():
            return target

    candidates = []
    for pattern in (
        f"experiment6_atlahs_dragonfly_production_workload_*/{summary_name}",
    ):
        candidates += list(results_root.glob(pattern))
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime).parent.resolve()
    raise SystemExit(f"cannot find an ATLAHS Dragonfly run under {results_root}")


def load_manifest(experiment_dir):
    for name in ("manifest.json", "experiment_6_manifest.json"):
        path = experiment_dir / name
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return json.load(f)
    return {}


def routing_style(routing):
    return ROUTING_STYLES.get(routing, {"label": routing, "color": DEFAULT_COLOR})


def routing_sort_key(row):
    return (
        integer(row.get("h"), 0),
        ROUTING_ORDER.get(row.get("routing", ""), 99),
        row.get("routing", ""),
        row.get("case_id", ""),
    )


def successful_summary_rows(summary_path, include_failed):
    rows = read_csv(summary_path)
    if include_failed:
        return sorted(rows, key=routing_sort_key)
    return sorted([row for row in rows if str(row.get("rc")) == "0"], key=routing_sort_key)


def routing_state_count(row):
    rules = integer(row.get("rule_based_rules"), 0) or 0
    entries = integer(row.get("routing_entries"), 0) or 0
    return max(rules, entries)


def normalize_rows(rows, manifest, summary_path):
    trace_stats = manifest.get("trace_stats", {}) if isinstance(manifest, dict) else {}
    normalized = []
    for row in rows:
        init_peak_mem_gb = gb_from_kb(row.get("init_peak_mem_kb"))
        exec_peak_mem_gb = number(row.get("exec_peak_mem_gb"))
        if exec_peak_mem_gb is None:
            exec_peak_mem_gb = gb_from_kb(row.get("exec_peak_mem_kb"))
        normalized.append({
            "case_id": row.get("case_id", ""),
            "routing": row.get("routing", ""),
            "h": integer(row.get("h"), 0),
            "g": integer(row.get("g"), 0),
            "a": integer(row.get("a"), 0),
            "p": integer(row.get("p"), 0),
            "dragonfly_hosts": integer(row.get("dragonfly_hosts"), 0),
            "trace_required_hosts": integer(row.get("trace_required_hosts"), 0),
            "trace_unique_ranks": integer(row.get("trace_unique_ranks"), 0),
            "traffic_trace_flows": integer(row.get("traffic_trace_flows"), 0),
            "packet_size": integer(row.get("packet_size"), 0),
            "init_s": number(row.get("init_s")),
            "exec_s": number(row.get("exec_s")),
            "wall_s": number(row.get("wall_s")),
            "init_peak_mem_gb": init_peak_mem_gb,
            "exec_peak_mem_gb": exec_peak_mem_gb,
            "rule_based_rules": integer(row.get("rule_based_rules"), 0),
            "routing_entries": integer(row.get("routing_entries"), 0),
            "routing_state_count": routing_state_count(row),
            "applications": integer(row.get("applications"), 0),
            "forward_count": integer(row.get("forward_count"), 0),
            "trace_total_bytes_scanned": integer(trace_stats.get("total_bytes_scanned"), 0),
            "trace_min_start_s": number(trace_stats.get("min_start_s"), 0.0),
            "trace_max_start_s": number(trace_stats.get("max_start_s"), 0.0),
            "source_summary": str(summary_path),
        })
    return normalized


def format_cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_normalized_stats(rows, out_dir):
    fields = [
        "case_id",
        "routing",
        "h",
        "g",
        "a",
        "p",
        "dragonfly_hosts",
        "trace_required_hosts",
        "trace_unique_ranks",
        "traffic_trace_flows",
        "packet_size",
        "init_s",
        "exec_s",
        "wall_s",
        "init_peak_mem_gb",
        "exec_peak_mem_gb",
        "rule_based_rules",
        "routing_entries",
        "routing_state_count",
        "applications",
        "forward_count",
        "trace_total_bytes_scanned",
        "trace_min_start_s",
        "trace_max_start_s",
        "source_summary",
    ]
    path = out_dir / "figure12_atlahs_dragonfly.csv"
    formatted = [{field: format_cell(row.get(field)) for field in fields} for row in rows]
    write_csv(path, fields, formatted)
    return path


def row_label(row, show_h):
    routing = routing_style(row["routing"])["label"]
    if show_h:
        return f"h={row['h']}\n{routing}"
    return routing


def format_value(value):
    if value is None:
        return ""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def format_time_value(value):
    if value is None:
        return ""
    if value >= 1000:
        return f"{int(value)}"
    return format_value(value)


def apply_axis_style(ax, values, log_y):
    ax.set_axisbelow(True)
    ax.grid(True, which="major", axis="y", color="#d9d9d9", linewidth=0.7, alpha=0.7)
    ax.grid(False, which="minor", axis="y")
    ax.tick_params(direction="in", top=False, right=True, labelsize=TICK_FONTSIZE)
    for spine in ax.spines.values():
        spine.set_linewidth(0.9)

    clean = [value for value in values if value is not None and value > 0]
    if log_y:
        ax.set_yscale("log")
        if clean:
            bottom = 10 ** math.floor(math.log10(min(clean)))
            top = 10 ** math.ceil(math.log10(max(clean) * 1.25))
            if bottom == top:
                top *= 10
            ax.set_ylim(bottom, top)
            first_exp = int(math.floor(math.log10(bottom)))
            last_exp = int(math.ceil(math.log10(top)))
            ticks = [10 ** exp for exp in range(first_exp, last_exp + 1, 2)]
            ax.yaxis.set_major_locator(FixedLocator(ticks))
            ax.yaxis.set_major_formatter(LogFormatterMathtext(base=10))
    else:
        if clean:
            ax.set_ylim(bottom=0.0, top=max(clean) * 1.16)
        ax.yaxis.set_major_locator(MultipleLocator(0.5))


def annotate_bars(ax, bars, rotate=False, value_formatter=format_value):
    for bar in bars:
        height = bar.get_height()
        if not math.isfinite(height) or height <= 0:
            continue
        ax.annotate(
            value_formatter(height),
            xy=(bar.get_x() + bar.get_width() / 2.0, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=ANNOTATION_FONTSIZE,
            rotation=0,
            zorder=4,
        )


def metric_value(row, field):
    value = row.get(field)
    if value is None:
        return 0.0
    return value


def plot_metric_axis(ax, rows, metric_specs, ylabel, log_y, title, show_h):
    x_step = 0.72 if len(rows) <= 3 else 1.0
    x = [idx * x_step for idx in range(len(rows))]
    width = min(0.56 / max(1, len(metric_specs)), 0.22)
    bar_spacing = width * 1.12
    all_values = []
    for idx, spec in enumerate(metric_specs):
        offset = (idx - (len(metric_specs) - 1) / 2.0) * bar_spacing
        values = [metric_value(row, spec["field"]) for row in rows]
        all_values += values
        bars = ax.bar(
            [pos + offset for pos in x],
            values,
            width=width,
            label=spec["label"],
            color=spec["color"],
            edgecolor="#333333",
            linewidth=0.45,
            zorder=3,
        )
        annotate_bars(ax, bars, rotate=len(rows) * len(metric_specs) > 4)

    ax.set_xticks(x)
    ax.set_xticklabels([row_label(row, show_h) for row in rows])
    group_half_width = ((len(metric_specs) - 1) * bar_spacing + width) / 2.0
    side_padding = max(0.16, group_half_width + 0.12)
    ax.set_xlim(x[0] - side_padding, x[-1] + side_padding)
    ax.set_ylabel(ylabel, fontsize=LABEL_FONTSIZE)
    if title:
        ax.set_title(title, fontsize=10, fontweight="bold")
    apply_axis_style(ax, all_values, log_y)
    if len(metric_specs) > 1:
        ax.legend(
            loc="upper left",
            frameon=True,
            framealpha=0.82,
            facecolor="white",
            edgecolor="none",
            fontsize=LEGEND_FONTSIZE,
        )


def plot_paper_axis(ax, rows, metric_specs, ylabel, log_y, show_h, value_formatter=format_value):
    x = list(range(len(rows)))
    width = 0.34
    offsets = [
        (idx - (len(metric_specs) - 1) / 2.0) * width * 1.08
        for idx in range(len(metric_specs))
    ]
    all_values = []
    for offset, spec in zip(offsets, metric_specs):
        values = [metric_value(row, spec["field"]) for row in rows]
        all_values += values
        bars = ax.bar(
            [pos + offset for pos in x],
            values,
            width=width,
            label=spec["label"],
            color=spec["color"],
            edgecolor="#333333",
            linewidth=0.35,
            zorder=3,
        )
        annotate_bars(ax, bars, value_formatter=value_formatter)

    ax.set_xticks(x)
    ax.set_xticklabels([row_label(row, show_h) for row in rows], fontsize=TICK_FONTSIZE)
    ax.set_xlim(x[0] - 0.55, x[-1] + 0.55)
    ax.set_ylabel(ylabel, fontsize=LABEL_FONTSIZE)
    apply_axis_style(ax, all_values, log_y)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.18),
        ncol=2,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        handlelength=1.2,
        columnspacing=1.1,
        borderaxespad=0.0,
    )


def save_figure(fig, out_dir, name, formats):
    written = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.04)
        written.append(path)
    plt.close(fig)
    return written


def remove_combined_outputs(out_dir, formats):
    for fmt in formats:
        path = out_dir / f"figure12.{fmt}"
        if path.exists():
            path.unlink()


def plot_single(rows, metric_specs, ylabel, log_y, title, name, out_dir, formats, show_h):
    fig_width = max(4.4, 1.25 * len(rows) + 2.4)
    fig, ax = plt.subplots(figsize=(fig_width, 2.9))
    plot_metric_axis(ax, rows, metric_specs, ylabel, log_y, title, show_h)
    fig.tight_layout()
    return save_figure(fig, out_dir, name, formats)


def legend_handles(rows):
    seen = []
    handles = []
    for row in rows:
        routing = row["routing"]
        if routing in seen:
            continue
        seen.append(routing)
        style = routing_style(routing)
        handles.append(Patch(facecolor=style["color"], edgecolor="#333333", label=style["label"]))
    return handles


def plot_overview(rows, out_dir, formats, show_h):
    written = []
    fig, ax = plt.subplots(figsize=PANEL_FIGSIZE)
    plot_paper_axis(
        ax,
        rows,
        [
            {"field": "init_peak_mem_gb", "label": "Initialization", "color": BAR_COLORS["initialization"]},
            {"field": "exec_peak_mem_gb", "label": "Execution", "color": BAR_COLORS["execution"]},
        ],
        "Peak memory (GB)",
        False,
        show_h,
    )
    fig.subplots_adjust(left=0.17, right=0.99, bottom=0.15, top=0.82)
    written += save_figure(fig, out_dir, "figure12a", formats)

    fig, ax = plt.subplots(figsize=PANEL_FIGSIZE)
    plot_paper_axis(
        ax,
        rows,
        [
            {"field": "init_s", "label": "Initialization", "color": BAR_COLORS["initialization"]},
            {"field": "exec_s", "label": "Execution", "color": BAR_COLORS["execution"]},
        ],
        "Time (s)",
        True,
        show_h,
        value_formatter=format_time_value,
    )
    fig.subplots_adjust(left=0.18, right=0.99, bottom=0.15, top=0.82)
    written += save_figure(fig, out_dir, "figure12b", formats)
    return written


def plot_workload_caption(rows, manifest, out_dir, formats):
    if not rows:
        return []
    first = rows[0]
    trace_stats = manifest.get("trace_stats", {}) if isinstance(manifest, dict) else {}
    text_lines = [
        "ATLAHS Dragonfly trace replay",
        f"Trace ranks: {first['trace_required_hosts']:,}",
        f"Dragonfly hosts: {first['dragonfly_hosts']:,} (h={first['h']}, g={first['g']}, a={first['a']}, p={first['p']})",
        f"Replayed flows: {first['traffic_trace_flows']:,}",
        f"Packet size: {first['packet_size']:,} B",
    ]
    total_bytes = integer(trace_stats.get("total_bytes_scanned"), 0)
    if total_bytes:
        text_lines.append(f"Traffic bytes scanned: {total_bytes / (1024.0 ** 3):.2f} GiB")

    fig, ax = plt.subplots(figsize=(6.4, 1.75))
    ax.axis("off")
    ax.text(
        0.0,
        0.95,
        "\n".join(text_lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=11,
        linespacing=1.35,
    )
    return save_figure(fig, out_dir, "atlahs_dragonfly_workload_summary", formats)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", default=None, help="Directory containing latest/current result pointers.")
    parser.add_argument("--experiment-dir", default=None, help="ATLAHS result directory or summary CSV.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--summary-name", default=DEFAULT_SUMMARY_NAME)
    parser.add_argument("--formats", default="pdf,png")
    parser.add_argument("--include-failed", action="store_true", help="Plot failed rows too.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    results_root = Path(args.results_root).resolve() if args.results_root else script_dir / "results"
    experiment_dir = resolve_experiment_dir(results_root, args.experiment_dir, args.summary_name)
    summary_path = experiment_dir / args.summary_name
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else experiment_dir / "figures" / "figure12"
    formats = parse_formats(args.formats)
    ensure_dir(out_dir)
    remove_combined_outputs(out_dir, formats)

    summary_rows = successful_summary_rows(summary_path, args.include_failed)
    if not summary_rows:
        raise SystemExit(f"no successful ATLAHS rows found in {summary_path}")
    manifest = load_manifest(experiment_dir)
    rows = normalize_rows(summary_rows, manifest, summary_path)
    show_h = len({row["h"] for row in rows}) > 1

    written = [write_normalized_stats(rows, out_dir)]
    written += plot_overview(rows, out_dir, formats, show_h)

    print(f"atlahs_results={experiment_dir}")
    print(f"atlahs_figures_dir={out_dir}")
    print(f"atlahs_summary={summary_path}")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
