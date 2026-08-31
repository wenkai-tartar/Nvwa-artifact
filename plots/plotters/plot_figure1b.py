#!/usr/bin/env python3
import argparse
import csv
import math
import os
from collections import defaultdict
from pathlib import Path
from statistics import fmean

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "nvwa-ae-matplotlib"))

plt = None

FIGSIZE = (3.85, 2.35)
LEGEND_FONTSIZE = 8.2
LABEL_FONTSIZE = 9.5
TICK_FONTSIZE = 8.0
ANNOTATION_FONTSIZE = 7.8
BAR_WIDTH = 0.62
BAR_LINEWIDTH = 0.5
GRID_ALPHA = 0.45
LEGEND_COLUMN_SPACING = 1.35
LEGEND_HANDLE_LENGTH = 1.1
LEGEND_Y_ANCHOR = 0.93
TIGHT_BBOX_TOP_CROP_PT = 1.0
TIGHT_BBOX_BOTTOM_PAD_PT = 0.17


def ensure_matplotlib():
    global plt
    if plt is not None:
        return
    import matplotlib

    from plot_style import configure_matplotlib

    configure_matplotlib(matplotlib)
    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot

    plt = pyplot


SYSTEM_RUNS = [
    {
        "system": "ns-3",
        "routing": "Global",
        "directory": "ns3_global",
        "color": "#4C78A8",
        "marker": "o",
    },
    {
        "system": "ns-3-datacenter",
        "routing": "NodeBfs",
        "directory": "ns3_datacenter_nodebfs",
        "color": "#F58518",
        "marker": "s",
    },
    {
        "system": "Nvwa",
        "routing": "RuleBased",
        "directory": "nvwa_rulebased",
        "color": "#54A24B",
        "marker": "^",
    },
]

ROUTING_ALIASES = {
    "global": "Global",
    "ns3global": "Global",
    "nodebfs": "NodeBfs",
    "ns3datacenternodebfs": "NodeBfs",
    "datacenternodebfs": "NodeBfs",
    "rulebased": "RuleBased",
    "nvwarulebased": "RuleBased",
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def number(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def mean(values):
    clean = [v for v in values if v is not None and math.isfinite(v)]
    return fmean(clean) if clean else 0.0


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def normalize_token(text):
    return text.strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def canonical_routing(text):
    token = normalize_token(text)
    if token not in ROUTING_ALIASES:
        raise SystemExit(f"Unknown routing '{text}'; use Global, NodeBfs, RuleBased, or all")
    return ROUTING_ALIASES[token]


def parse_routings(text):
    values = []
    for raw in text.split(","):
        part = raw.strip()
        if not part:
            continue
        if normalize_token(part) == "all":
            for item in SYSTEM_RUNS:
                if item["routing"] not in values:
                    values.append(item["routing"])
            continue
        routing = canonical_routing(part)
        if routing not in values:
            values.append(routing)
    if not values:
        raise SystemExit("No routing selected")
    return values


def routing_slug(routing):
    return normalize_token(routing)


def routing_metadata(routing):
    for item in SYSTEM_RUNS:
        if item["routing"] == routing:
            return item
    raise SystemExit(f"No metadata for routing={routing}")


def save(fig, out_dir, name, formats):
    from matplotlib.transforms import Bbox

    fig.canvas.draw()
    bbox = fig.get_tightbbox(fig.canvas.get_renderer()).padded(0.03)
    if name == "figure1b":
        bbox = Bbox.from_extents(
            bbox.x0,
            bbox.y0 - TIGHT_BBOX_BOTTOM_PAD_PT / 72.0,
            bbox.x1,
            bbox.y1 - TIGHT_BBOX_TOP_CROP_PT / 72.0,
        )

    paths = []
    for fmt in formats:
        path = out_dir / f"{name}.{fmt}"
        fig.savefig(path, bbox_inches=bbox, pad_inches=0.0)
        paths.append(path)
    plt.close(fig)
    return paths


ROUTING_MEMORY_CATEGORIES = {
    "global_routing",
    "node_bfs_routing",
    "node_bfs_strict_routing",
    "rule_based_routing",
}


ROUTING_MEMORY_PREFIXES = (
    "routing_global_",
    "routing_node_bfs_",
    "routing_rulebased_",
)


def is_routing_stage(stage, category=""):
    if stage == "routing_helper_setup":
        return False
    if stage == "routing_state":
        return True
    if category in ROUTING_MEMORY_CATEGORIES:
        return True
    return any(stage.startswith(prefix) for prefix in ROUTING_MEMORY_PREFIXES)


def stage_bucket(stage, category=""):
    if stage in {"topology_build", "template_build", "topology_seed", "address_registration"}:
        return "topology"
    if is_routing_stage(stage, category):
        return "routing_state"
    return "others"


def is_traffic_application_stage(stage):
    return stage == "applications" or stage == "traffic_graph" or stage.startswith("traffic_")


def pct(value, total):
    return 100.0 * value / total if total > 0 else 0.0


def mb_label(value):
    if value >= 100.0:
        return f"{value:.0f} MB"
    if value >= 10.0:
        return f"{value:.1f} MB"
    return f"{value:.2f} MB"


FIGURE1B_FIELDS = [
    "k",
    "fat_tree",
    "topology_mb",
    "routing_state_mb",
    "others_mb",
    "traffic_application_setup_mb",
    "total_positive_delta_mb",
    "topology_pct",
    "routing_state_pct",
    "others_pct",
]
DEFAULT_MEMORY_PROFILE_NAME = "experiment_2_memory_profile.csv"


def figure1b_table(run_dir, routing, memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    rows = [row for row in read_csv(run_dir / memory_profile_name) if row.get("routing") == routing]
    if not rows:
        return []

    per_case = defaultdict(lambda: defaultdict(float))
    traffic_setup_by_case = defaultdict(float)
    for row in rows:
        k = int(number(row.get("k"), 0))
        case_id = row.get("case_id")
        if not case_id:
            continue
        delta = max(number(row.get("delta_kb"), 0.0), 0.0) / 1024.0
        stage = row.get("stage", "")
        per_case[(case_id, k)][stage_bucket(stage, row.get("category", ""))] += delta
        if is_traffic_application_stage(stage):
            traffic_setup_by_case[(case_id, k)] += delta

    per_k = defaultdict(lambda: defaultdict(list))
    traffic_setup_by_k = defaultdict(list)
    for (_, k), buckets in per_case.items():
        for bucket in ["topology", "routing_state", "others"]:
            per_k[k][bucket].append(buckets.get(bucket, 0.0))
    for (_, k), value in traffic_setup_by_case.items():
        traffic_setup_by_k[k].append(value)

    table = []
    for k in sorted(per_k):
        topology = mean(per_k[k]["topology"])
        routing_state = mean(per_k[k]["routing_state"])
        others = mean(per_k[k]["others"])
        total = topology + routing_state + others
        traffic_setup = mean(traffic_setup_by_k[k])
        row = {
            "k": k,
            "fat_tree": f"FT{k}",
            "topology_mb": f"{topology:.6f}",
            "routing_state_mb": f"{routing_state:.6f}",
            "others_mb": f"{others:.6f}",
            "traffic_application_setup_mb": f"{traffic_setup:.6f}",
            "total_positive_delta_mb": f"{total:.6f}",
            "topology_pct": f"{pct(topology, total):.2f}",
            "routing_state_pct": f"{pct(routing_state, total):.2f}",
            "others_pct": f"{pct(others, total):.2f}",
        }
        table.append(row)

    return table


def draw_figure1b_table(table, out_dir, name, formats):
    ensure_matplotlib()
    if not table:
        raise SystemExit(f"No rows to plot for {name}")

    labels = [row["fat_tree"] for row in table]
    buckets = [
        ("routing_state_pct", "Routing table", "#F58518", "////"),
        ("topology_pct", "Topology", "#4C78A8", None),
        ("others_pct", "Others", "#54A24B", None),
    ]
    x = list(range(len(labels)))
    bottoms = [0.0 for _ in labels]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for field, label, color, hatch in buckets:
        values = [float(row[field]) for row in table]
        ax.bar(
            x,
            values,
            bottom=bottoms,
            width=BAR_WIDTH,
            color=color,
            edgecolor="black",
            linewidth=BAR_LINEWIDTH,
            hatch=hatch,
            label=label,
            zorder=3,
        )
        bottoms = [b + v for b, v in zip(bottoms, values)]
    for idx, row in enumerate(table):
        ax.text(
            idx,
            103.0,
            mb_label(float(row["total_positive_delta_mb"])),
            ha="center",
            va="bottom",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=TICK_FONTSIZE)
    ax.set_xlabel("Fat-tree scale (k)", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("Init. memory composition (%)", fontsize=LABEL_FONTSIZE)
    ax.set_ylim(0, 118)
    ax.tick_params(axis="y", labelsize=TICK_FONTSIZE)
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
        bbox_to_anchor=(0.5, LEGEND_Y_ANCHOR),
        ncol=3,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        columnspacing=LEGEND_COLUMN_SPACING,
        handlelength=LEGEND_HANDLE_LENGTH,
    )

    return save(fig, out_dir, name, formats)


def print_memory_profile_composition(table, label):
    print(f"memory_profile_composition[{label}]:")
    for row in table:
        print(
            f"{row['fat_tree']}: topology {row['topology_pct']}%, "
            f"routing {row['routing_state_pct']}%, others {row['others_pct']}%"
        )
        print(f"  others traffic/application setup = {float(row['traffic_application_setup_mb']):.3f} MB")


def plot_figure1b(run_dir, out_dir, routing, formats, name="figure1b", memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    table = figure1b_table(run_dir, routing, memory_profile_name)
    if not table:
        raise SystemExit(f"No memory-profile rows for routing={routing} under {run_dir}")

    profile_path = out_dir / f"{name}_initialization_memory_profile.csv"
    if name == "figure1b":
        profile_path = out_dir / "figure1b_initialization_memory_profile.csv"
    write_csv(profile_path, FIGURE1B_FIELDS, table)

    print_memory_profile_composition(table, routing)
    return [profile_path] + draw_figure1b_table(table, out_dir, name, formats)


def collect_figure1b_tables(base_dir, routings, memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    collected = []
    for routing in routings:
        run_dir = resolve_figure1b_run_dir(base_dir, routing, required=False, memory_profile_name=memory_profile_name)
        if run_dir is None:
            print(f"[WARN] no {memory_profile_name} found for routing={routing} under {base_dir}")
            continue
        table = figure1b_table(run_dir, routing, memory_profile_name)
        if not table:
            print(f"[WARN] no memory-profile rows for routing={routing} under {run_dir}")
            continue
        metadata = routing_metadata(routing)
        collected.append({
            "routing": routing,
            "system": metadata["system"],
            "run_dir": run_dir,
            "table": table,
        })
    if not collected:
        raise SystemExit(f"No Figure 1(b) memory-profile data found under {base_dir}")
    return collected


def plot_figure1b_comparison(base_dir, out_dir, routings, formats, memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    ensure_matplotlib()
    collected = collect_figure1b_tables(base_dir, routings, memory_profile_name)

    routing_order = {routing: idx for idx, routing in enumerate(routings)}
    rows = []
    for item in collected:
        for row in item["table"]:
            rows.append({
                "system": item["system"],
                "routing": item["routing"],
                **row,
            })
    rows.sort(key=lambda row: (int(row["k"]), routing_order.get(row["routing"], 999)))

    fields = ["system", "routing"] + FIGURE1B_FIELDS
    profile_path = out_dir / "figure1b_comparison_initialization_memory_profile.csv"
    write_csv(profile_path, fields, rows)

    buckets = [
        ("topology_pct", "Topology construction", "#4C78A8", None),
        ("routing_state_pct", "Routing state", "#F58518", "////"),
        ("others_pct", "Others", "#54A24B", None),
    ]
    labels = [f"{row['fat_tree']}\n{row['routing']}" for row in rows]
    x = list(range(len(rows)))
    bottoms = [0.0 for _ in rows]

    fig_width = max(6.2, 0.72 * len(rows) + 1.4)
    fig, ax = plt.subplots(figsize=(fig_width, 3.8))
    for field, label, color, hatch in buckets:
        values = [float(row[field]) for row in rows]
        ax.bar(
            x,
            values,
            bottom=bottoms,
            width=0.62,
            color=color,
            edgecolor="black",
            linewidth=0.6,
            hatch=hatch,
            label=label,
            zorder=3,
        )
        bottoms = [b + v for b, v in zip(bottoms, values)]

    for idx, row in enumerate(rows):
        ax.text(
            idx,
            103.0,
            mb_label(float(row["total_positive_delta_mb"])),
            ha="center",
            va="bottom",
            fontsize=7,
        )

    group_positions = defaultdict(list)
    for idx, row in enumerate(rows):
        group_positions[row["fat_tree"]].append(idx)
    for positions in list(group_positions.values())[:-1]:
        ax.axvline(max(positions) + 0.5, color="0.82", linewidth=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlabel("Fat-tree scale (k) and routing")
    ax.set_ylabel("Init. memory composition (%)")
    ax.set_ylim(0, 112)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.17), ncol=3, frameon=True, fontsize=8)
    fig.tight_layout()

    print("memory_profile_comparison:")
    for row in rows:
        print(
            f"{row['fat_tree']} {row['routing']}: topology {row['topology_pct']}%, "
            f"routing {row['routing_state_pct']}%, others {row['others_pct']}%"
        )
    return [profile_path] + save(fig, out_dir, "figure1b_comparison", formats)


def plot_figure1b_for_routings(base_dir, out_dir, routings, formats, mode, memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    if mode == "auto":
        mode = "separate" if len(routings) == 1 else "combined"

    written = []
    if mode in {"separate", "both"}:
        for routing in routings:
            run_dir = resolve_figure1b_run_dir(base_dir, routing, required=False, memory_profile_name=memory_profile_name)
            if run_dir is None:
                print(f"[WARN] no {memory_profile_name} found for routing={routing} under {base_dir}")
                continue
            name = "figure1b" if len(routings) == 1 else f"figure1b_{routing_slug(routing)}"
            written += plot_figure1b(run_dir, out_dir, routing, formats, name=name, memory_profile_name=memory_profile_name)

    if mode in {"combined", "both"}:
        written += plot_figure1b_comparison(base_dir, out_dir, routings, formats, memory_profile_name)

    if not written:
        raise SystemExit(f"No Figure 1(b) output written for routings={','.join(routings)}")
    return written


def resolve_figure1b_run_dir(run_dir, routing="NodeBfs", required=True, memory_profile_name=DEFAULT_MEMORY_PROFILE_NAME):
    run_dir = Path(run_dir)
    if (run_dir / memory_profile_name).exists():
        return run_dir

    metadata = routing_metadata(routing)
    candidate = run_dir / metadata["directory"]
    if (candidate / memory_profile_name).exists():
        return candidate

    for item in SYSTEM_RUNS:
        candidate = run_dir / item["directory"]
        if (candidate / memory_profile_name).exists():
            rows = read_csv(candidate / memory_profile_name)
            if any(row.get("routing") == routing for row in rows):
                return candidate

    if required:
        raise SystemExit(f"Cannot find {memory_profile_name} for routing={routing} under {run_dir}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--routing", default=None)
    parser.add_argument("--routings", default=None)
    parser.add_argument("--figure", choices=["figure1b"], default="figure1b")
    parser.add_argument("--figure1b-mode", choices=["auto", "separate", "combined", "both"], default="auto")
    parser.add_argument("--memory-profile-name", default=DEFAULT_MEMORY_PROFILE_NAME)
    parser.add_argument("--formats", default="pdf,png")
    args = parser.parse_args()

    base_dir = Path(args.experiment_dir or args.run_dir or ".").resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else base_dir / "figures" / "figure1b"
    formats = [fmt.strip() for fmt in args.formats.split(",") if fmt.strip()]
    routings = parse_routings(args.routings or args.routing or "NodeBfs")
    ensure_dir(out_dir)

    written = plot_figure1b_for_routings(
        base_dir,
        out_dir,
        routings,
        formats,
        args.figure1b_mode,
        args.memory_profile_name,
    )

    print(f"figures_dir={out_dir}")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
