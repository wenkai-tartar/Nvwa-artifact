#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.ticker import LogLocator, LogFormatterMathtext, MultipleLocator
from archived_paths import data_path, output_path

# =========================
# 你的“满意版”style
# =========================
mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42
mpl.rcParams["text.usetex"] = False
mpl.rcParams["font.family"] = "serif"
mpl.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]
mpl.rcParams["font.sans-serif"] = ["Times New Roman", "DejaVu Sans"]
mpl.rcParams["mathtext.fontset"] = "stix"
mpl.rcParams["xtick.direction"] = "in"
mpl.rcParams["ytick.direction"] = "in"

mpl.rcParams["legend.frameon"] = True
mpl.rcParams["legend.facecolor"] = "white"
mpl.rcParams["legend.framealpha"] = 1.0
mpl.rcParams["legend.edgecolor"] = "white"

plt.rcParams.update({
    "figure.figsize": (8, 5),
    "font.size": 30,
    "axes.labelsize": 30,
    "xtick.labelsize": 30,
    "ytick.labelsize": 30,
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.linewidth": 0.1,
    "grid.color": "lightgrey",
})

LINEWIDTH = 4.5
MARKERSIZE = 20
TICK_WIDTH = 2.5
TICK_LENGTH = 5
SPINE_W = 2.0


def beautify_ax(ax, right=False):
    ax.tick_params(
        direction="in",
        width=TICK_WIDTH,
        length=TICK_LENGTH,
        top=True,
        right=right,
        labeltop=False,
        labelright=False,
    )
    for side in ["bottom", "left", "right", "top"]:
        ax.spines[side].set_linewidth(SPINE_W)
    ax.xaxis.grid(True, which="major")


def apply_log_minor_ticks(ax):
    ax.set_yscale("log")

    # 主刻度：10^n
    ax.yaxis.set_major_locator(LogLocator(base=10.0, numticks=12))
    ax.yaxis.set_major_formatter(LogFormatterMathtext(base=10.0))

    # 次刻度：2~9 * 10^n
    ax.yaxis.set_minor_locator(
        LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=100)
    )

    # 显示次刻度标签（需要更密的 y 轴时有用）
    ax.yaxis.set_minor_formatter(LogFormatterMathtext(base=10.0, labelOnlyBase=False))
    ax.tick_params(axis="y", which="minor", labelsize=20)


def dedup_legend(ax, loc="best", **kwargs):
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc=loc, **kwargs)


def parse_param_from_name(name: str, key: str):
    m = re.search(rf"-{key}(\d+)-", name)
    return int(m.group(1)) if m else None


def agg_xy(df_sub: pd.DataFrame, metric: str, key: str):
    tmp = df_sub.copy()
    tmp["x"] = tmp["name"].apply(lambda s: parse_param_from_name(s, key))
    tmp = tmp.dropna(subset=["x", metric])
    g = tmp.groupby("x", as_index=False)[metric].mean().sort_values("x")
    return g["x"].to_numpy(), g[metric].to_numpy()


def set_categorical_ticks(ax, xvals, prefix):
    xvals = sorted(list(set(map(int, xvals))))
    pos_map = {v: i for i, v in enumerate(xvals)}
    positions = np.arange(len(xvals))
    labels = [f"{prefix}{v}" for v in xvals]

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_xlim(-0.5, len(xvals) - 0.5)
    return pos_map


def plot_one(
    out_pdf,
    curves,
    xkey,
    xtick_prefix,
    ylabel,
    metric,
    logy=False,
    legend_loc="upper left",
    ylim=None,
    y_major_step=None,   # ✅ 新增：线性 y 轴步长（控制“密/稀”）
    extra_out_pdfs=None,
):
    fig, ax = plt.subplots()
    beautify_ax(ax)

    if logy:
        apply_log_minor_ticks(ax)

    # 收集本图所有 x 值（用于等间距类别轴）
    all_x = []
    for c in curves:
        sub = c["df_filter"](DF)
        if len(sub) == 0:
            continue
        xs = sub["name"].apply(lambda s: parse_param_from_name(s, xkey)).dropna().astype(int).tolist()
        all_x.extend(xs)

    if len(all_x) == 0:
        print(f"[WARN] No x values parsed for {out_pdf} (key={xkey})")
        plt.close(fig)
        return

    pos_map = set_categorical_ticks(ax, all_x, prefix=xtick_prefix)

    # 画线：只画真实存在点，不补齐
    for c in curves:
        sub = c["df_filter"](DF)
        if len(sub) == 0:
            continue

        x_num, y = agg_xy(sub, metric=metric, key=xkey)
        if len(x_num) == 0:
            continue

        x_pos = [pos_map[int(v)] for v in x_num]

        ax.plot(
            x_pos, y,
            linestyle="-",
            linewidth=LINEWIDTH,
            marker=c["marker"],
            markersize=MARKERSIZE,
            color=c["color"],
            label=c["label"],
        )

    # 不要 x 轴总名字
    ax.set_xlabel("")
    ax.set_ylabel(ylabel)

    # ✅ 线性 y 轴：按图控制刻度密度
    if not logy:
        if y_major_step is None:
            y_major_step = 10  # 默认密一点
        ax.yaxis.set_major_locator(MultipleLocator(y_major_step))

    if ylim is not None:
        ax.set_ylim(ylim[0], ylim[1])

    dedup_legend(ax, loc=legend_loc, fontsize=20)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    for path in [out_pdf] + list(extra_out_pdfs or []):
        fig.savefig(path, bbox_inches="tight", dpi=300)
        print(f"Saved {path}")
    plt.close(fig)


# =========================
# 读数据
# =========================
CSV_PATH = data_path("nonminimal-time-mem.csv")
DF = pd.read_csv(CSV_PATH)
DF = DF[["name", "variant", "exec_s", "exec_peak_mem_gb"]].copy()

# =========================
# DF 图：dragonfly（h -> DF{h}）
# =========================
df_curves = [
    {"label": "valiant", "color": "C0", "marker": "^",
     "df_filter": lambda d: d[d["name"].str.startswith("dragonfly_valiant-") & (d["variant"] == "nonminimal")]},
    {"label": "UGAL",    "color": "C2", "marker": "o",
     "df_filter": lambda d: d[d["name"].str.startswith("dragonfly_ugal-") & (d["variant"] == "nonminimal")]},
    {"label": "shortest", "color": "C1", "marker": "s",
     "df_filter": lambda d: d[d["name"].str.startswith("dragonfly_valiant-") & (d["variant"] == "baseline")]},
]

# =========================
# TR 图：torus（d -> TR{d}）
# =========================
tr_curves = [
    {"label": "detour1", "color": "C0", "marker": "^",
     "df_filter": lambda d: d[d["name"].str.startswith("torus_detour1-") & (d["variant"] == "nonminimal")]},
    {"label": "detour2", "color": "C1", "marker": "s",
     "df_filter": lambda d: d[d["name"].str.startswith("torus_detour2-") & (d["variant"] == "nonminimal")]},
    {"label": "shortest", "color": "C2", "marker": "o",
     "df_filter": lambda d: d[d["name"].str.startswith("torus_detour1-") & (d["variant"] == "baseline")]},
]

# =========================
# 输出 4 张图 4 个 PDF
# =========================
plot_one(
    out_pdf=output_path("nonminimal-dragonfly-exec.pdf"),
    curves=df_curves,
    xkey="h",
    xtick_prefix="DF",
    ylabel="Execution time (s)",
    metric="exec_s",
    logy=True,
    extra_out_pdfs=[output_path("df_time.pdf")],
)

# ✅ 这张（dragonfly-mem）y 轴过密：把 major step 调大即可（20/25/50 任选）
plot_one(
    out_pdf=output_path("nonminimal-dragonfly-mem.pdf"),
    curves=df_curves,
    xkey="h",
    xtick_prefix="DF",
    ylabel="Peak memory (GB)",
    metric="exec_peak_mem_gb",
    logy=False,
    y_major_step=20,   # 👈 稀一点
    extra_out_pdfs=[output_path("df_memory.pdf")],
)

plot_one(
    out_pdf=output_path("nonminimal-torus-exec.pdf"),
    curves=tr_curves,
    xkey="d",
    xtick_prefix="TR",
    ylabel="Execution time (s)",
    metric="exec_s",
    logy=True,
    extra_out_pdfs=[output_path("tr_time.pdf")],
)

plot_one(
    out_pdf=output_path("nonminimal-torus-mem.pdf"),
    curves=tr_curves,
    xkey="d",
    xtick_prefix="TR",
    ylabel="Peak memory (GB)",
    metric="exec_peak_mem_gb",
    logy=False,
    y_major_step=10,   # 默认保持密一点（可不写）
    extra_out_pdfs=[output_path("tr_memory.pdf")],
)
