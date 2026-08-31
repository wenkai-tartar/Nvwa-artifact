#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import re
import matplotlib as mpl
from matplotlib.ticker import LogLocator
from archived_paths import data_path, output_path

# ============================================================
# Style：对齐你“满意版本”
# ============================================================
mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42
mpl.rcParams["text.usetex"] = False
mpl.rcParams["font.family"] = "serif"
mpl.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]
mpl.rcParams["font.sans-serif"] = ["Times New Roman", "DejaVu Sans"]
mpl.rcParams["mathtext.fontset"] = "stix"
mpl.rcParams["xtick.direction"] = "in"
mpl.rcParams["ytick.direction"] = "in"

# Legend：白底、不透明、边框白色（看起来像无边框）
mpl.rcParams["legend.frameon"] = True
mpl.rcParams["legend.facecolor"] = "white"
mpl.rcParams["legend.framealpha"] = 1.0
mpl.rcParams["legend.edgecolor"] = "white"

plt.rcParams.update({
    "figure.figsize": (8, 5),
    "font.size": 25,
    "axes.labelsize": 30,
    "xtick.labelsize": 25,
    "ytick.labelsize": 25,
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.linewidth": 0.1,
    "grid.color": "lightgrey",  # 浅灰虚线
})

# 颜色保持不变（C0/C1/C2），marker/线宽/点大小对齐满意版本
style_map = {
    "Nüwa":    {"marker": "^", "color": "C0"},
    "ns-3-dc": {"marker": "s", "color": "C1"},
    "ns-3":    {"marker": "o", "color": "C2"},
}

LINEWIDTH = 4.5
MARKERSIZE = 20
TICK_WIDTH = 2.5
TICK_LENGTH = 5
SPINE_W = 2.0


# ============================================================
# 数据读取
# ============================================================
csv_files = [
    data_path("fattree-time-mem-ar.csv"),
    data_path("dragonfly-time-mem-ar.csv"),
    data_path("torus-time-mem-ar.csv"),
]

dfs = []
for f in csv_files:
    df_tmp = pd.read_csv(f)
    df_tmp["source_file"] = str(f)
    dfs.append(df_tmp)

df = pd.concat(dfs, ignore_index=True)


def extract_param(name):
    if "fattree" in name:
        m = re.search(r"-k(\d+)-", name)
        return int(m.group(1)) if m else None
    elif "dragonfly" in name:
        m = re.search(r"-h(\d+)-", name)
        return int(m.group(1)) if m else None
    elif "torus" in name:
        m = re.search(r"-x(\d+)", name)
        return int(m.group(1)) if m else None
    return None


def extract_topology(name):
    if "fattree" in name:
        return "fattree"
    if "dragonfly" in name:
        return "dragonfly"
    if "torus" in name:
        return "torus"
    return "Unknown"


df["param"] = df["name"].apply(extract_param)
df["topology"] = df["name"].apply(extract_topology)

# 标准化 routing
df["routing"] = df["routing"].replace({
    "RuleBased": "Nüwa",
    "NodeBfs": "ns-3-dc",
    "NodeBfsWithHost": "ns-3-dc",
    "Global": "ns-3",
})


# ============================================================
# 绘图辅助
# ============================================================
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

    # x 主网格保持开启（rcParams 已开）
    ax.xaxis.grid(True, which="major")


def dedup_legend(ax, loc="best", **kwargs):
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc=loc, **kwargs)


def apply_log_minor_ticks(ax):
    ax.set_yscale("log")
    ax.yaxis.set_minor_locator(
        LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=10)
    )


def topo_tick_label(topo: str, v):
    if topo == "fattree":
        return f"FT{v}"
    if topo == "dragonfly":
        return f"DF{v}"
    if topo == "torus":
        return f"TR{v}"
    return str(v)


# ============================================================
# 通用绘图（折线图：等间距类别坐标；可选柱状图）
# ============================================================
def plot_metric(df_sub, topo, metric, ylabel, filename, logy=True, kind="line", ylim=None, xlim=None):
    fig, ax = plt.subplots()
    beautify_ax(ax, right=False)

    # 限制 Fat-tree 的 Execution time 只绘制到 k=64
    if topo == "fattree" and metric == "exec_s":
        df_sub = df_sub[df_sub["param"] <= 64]

    if logy:
        apply_log_minor_ticks(ax)

    xticks = sorted(df_sub["param"].dropna().unique())
    x_pos = np.arange(len(xticks))  # 等间距位置

    if kind == "bar":
        bar_width = 0.25
        for i, sys in enumerate(["Nüwa", "ns-3-dc", "ns-3"]):
            dfs_sys = df_sub[df_sub["routing"] == sys]
            if len(dfs_sys) == 0:
                continue
            y = [dfs_sys[dfs_sys["param"] == k][metric].mean() for k in xticks]
            ax.bar(
                x_pos + (i - 1) * bar_width,
                y,
                width=bar_width,
                label=sys,
            )

        ax.set_xticks(x_pos)
        ax.set_xticklabels([topo_tick_label(topo, v) for v in xticks], rotation=45, ha="right")

    else:
        # 折线图
        pos_map = {k: i for i, k in enumerate(xticks)}

    for sys in ["Nüwa", "ns-3-dc", "ns-3"]:
        dfs_sys = df_sub[df_sub["routing"] == sys]
        if len(dfs_sys) == 0:
            continue

        ks = sorted(dfs_sys["param"].dropna().unique())   # ✅ 只取这个系统真实有的点
        xs = [pos_map[k] for k in ks]
        ys = [dfs_sys[dfs_sys["param"] == k][metric].mean() for k in ks]

        ax.plot(
            xs, ys,
            linestyle="-",
            linewidth=LINEWIDTH,
            marker=style_map[sys]["marker"],
            markersize=MARKERSIZE,
            color=style_map[sys]["color"],
            label=sys,
        )

        ax.set_xticks(x_pos)
        ax.set_xticklabels([topo_tick_label(topo, v) for v in xticks], rotation=45, ha="right")

    ax.set_ylabel(ylabel)
    

    # 每张图不同的 y 轴范围
    if ylim is not None:
        ax.set_ylim(ylim[0], ylim[1])

    if xlim is not None:
        ax.set_xlim(xlim[0], xlim[1])

    # dedup_legend(ax, loc="best", fontsize=28)
    
    fig.tight_layout()
    fig.savefig(filename, bbox_inches="tight", dpi=300)
    print(f"Saved {filename}")


# ============================================================
# 分拓扑绘图
# ============================================================
for topo in ["fattree", "dragonfly", "torus"]:
    df_sub = df[df["topology"] == topo]
    if len(df_sub) == 0:
        continue

    suffix = ""
    if any(("ar" in f.name and topo in f.name) for f in csv_files):
        suffix += "-ar"
    if any(("aa" in f.name and topo in f.name) for f in csv_files):
        suffix += "-aa"

    # 你可以按 topo/metric 自己微调下面的 ylim（这里给示例范围）

    if topo == "fattree":
        plot_metric(
            df_sub, topo,
            metric="init_s",
            ylabel="Initialization time (s)",
            filename=output_path(f"init_{topo}{suffix}.pdf"),
            logy=True,
            kind="line",
            ylim=(1e-2, 1e6),
            xlim=(0, 11) 
        )

        plot_metric(
            df_sub, topo,
            metric="exec_s",
            ylabel="Execution time (s)",
            filename=output_path(f"exec_{topo}{suffix}.pdf"),
            logy=False,
            kind="line",
            ylim=(0, 1e4),
            # xlim=(0, 8) 
        )

    if topo == "dragonfly":
        plot_metric(
            df_sub, topo,
            metric="init_s",
            ylabel="Initialization time (s)",
            filename=output_path(f"init_{topo}{suffix}.pdf"),
            logy=True,
            kind="line",
            ylim=(1e-2, 1e6),
            xlim=(0, 6) 
        )

        plot_metric(
            df_sub, topo,
            metric="exec_s",
            ylabel="Execution time (s)",
            filename=output_path(f"exec_{topo}{suffix}.pdf"),
            logy=False,
            kind="line",
            ylim=(0, 100000),
            # xlim=(0, 8) 
        )

        plot_metric(
            df_sub, topo,
            metric="exec_peak_mem_gb",
            ylabel="Execution memory (GB)",
            filename=output_path(f"mem_{topo}{suffix}.pdf"),
            logy=False,
            kind="line",
            ylim=(0, 500),
        )

    if topo == "torus":
        plot_metric(
            df_sub, topo,
            metric="init_s",
            ylabel="Initialization time (s)",
            filename=output_path(f"init_{topo}{suffix}.pdf"),
            logy=True,
            kind="line",
            ylim=(1e-2, 1e6),
            xlim=(0, 6) 
        )

        plot_metric(
            df_sub, topo,
            metric="exec_s",
            ylabel="Execution time (s)",
            filename=output_path(f"exec_{topo}{suffix}.pdf"),
            logy=False,
            kind="line",
            ylim=(0, 75000),
        )

    # plot_metric(
    #     df_sub, topo,
    #     metric="exec_peak_mem_gb",
    #     ylabel="Execution memory (GB)",
    #     filename=output_path(f"mem_{topo}{suffix}.pdf"),
    #     logy=False,
    #     kind="line",
    #     ylim=None
    # )

    # plot_metric(
    #     df_sub, topo,
    #     metric="wall_s",
    #     ylabel="Total simulation time (s)",
    #     filename=output_path(f"total_{topo}{suffix}.pdf"),
    #     logy=True,
    #     kind="line",
    #     ylim=None
    # )
