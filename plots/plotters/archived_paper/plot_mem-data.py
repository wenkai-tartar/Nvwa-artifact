#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import re
import matplotlib as mpl
from matplotlib.ticker import LogLocator
from archived_paths import DATA_DIR, output_path

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
    "figure.figsize": (6, 5),
    "font.size": 25,
    "axes.labelsize": 25,
    "xtick.labelsize": 25,
    "ytick.labelsize": 25,
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

# 系统显示样式（颜色保持不变：C0/C1）
style_map = {
    "RuleBased": {"label": "Nüwa",    "marker": "^", "color": "C0"},
    "NodeBfs":   {"label": "ns-3-dc", "marker": "s", "color": "C1"},
}

data_dir = DATA_DIR
for fname in os.listdir(data_dir):
    if not fname.endswith(".csv"):
        continue
    if "-data-" not in fname:
        continue

    path = os.path.join(data_dir, fname)
    df = pd.read_csv(path)

    topo_match = re.match(r"(fattree|dragonfly|torus)-data-(k|h)?(\d+)", fname)
    if not topo_match:
        continue
    topo, level, param = topo_match.groups()
    topo_tag = f"{topo}_{level}{param}" if level else topo

    # 提取 data size 作为 x 轴（类别型等间距）
    df["data_size"] = df["name"].apply(
        lambda x: re.search(r"-(\d+MB)", x).group(1) if re.search(r"-(\d+MB)", x) else None
    )
    df = df.dropna(subset=["data_size"])
    sizes = sorted(df["data_size"].unique(), key=lambda x: int(x.replace("MB", "")))

    fig, ax = plt.subplots()
    beautify_ax(ax, right=False)

    # 类别型等间距横坐标
    x_pos = np.arange(len(sizes))
    pos_map = {s: i for i, s in enumerate(sizes)}

    for sys, style in style_map.items():
        sub = df[df["routing"] == sys]
        if len(sub) == 0:
            continue

        # ✅ 只画真实存在的数据点（避免“补齐”）
        ss = sorted(sub["data_size"].dropna().unique(), key=lambda x: int(x.replace("MB", "")))
        xs = [pos_map[s] for s in ss]
        ys = [sub[sub["data_size"] == s]["exec_s"].mean() for s in ss]

        ax.plot(
            xs, ys,
            linestyle="-",
            linewidth=LINEWIDTH,
            marker=style["marker"],
            markersize=MARKERSIZE,
            color=style["color"],
            label=style["label"],
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(sizes, rotation=45, ha="right")
    ax.set_ylabel("Execution time (s)")

    # ✅ 贴边（让第一个点靠近 y 轴）
    ax.set_xlim(-0.5, len(sizes) - 0.5)

    # 这份脚本你说不需要图内 legend（你用 legend1.pdf），所以不画 legend
    # 如果你想临时画一个用于检查，取消注释下面两行：
    ax.legend(loc="best", fontsize=20)
    # fig.tight_layout(rect=[0, 0, 1, 0.90])

    fig.tight_layout()
    
    outname = output_path(f"exec_{topo_tag}.pdf")
    fig.savefig(outname, bbox_inches="tight", dpi=300)
    print(f"Saved {outname}")
