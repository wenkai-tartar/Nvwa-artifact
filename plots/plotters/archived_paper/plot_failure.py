#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.ticker import LogLocator
from archived_paths import data_path, ensure_output_dir, output_path

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
    "figure.figsize": (8, 4.5),      # 单张图
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
MARKERSIZE = 16      # 想更大改 20
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
    ax.yaxis.set_minor_locator(
        LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=10)
    )


def dedup_legend(ax, loc="best", **kwargs):
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc=loc, **kwargs)


def extract_k(name: str):
    m = re.search(r"-k(\d+)-", name)
    return int(m.group(1)) if m else None


def prepare_series(df_sub: pd.DataFrame, metric: str):
    tmp = df_sub.copy()
    tmp["k"] = tmp["name"].apply(extract_k)
    tmp = tmp.dropna(subset=["k", metric])
    g = tmp.groupby("k", as_index=False)[metric].mean().sort_values("k")
    return g["k"].to_numpy(), g[metric].to_numpy()


# =========================
# 读取 CSV
# =========================
CSV_PATH = data_path("failure-Fattree-RuleBased-allreduce-1024KB.csv")
df = pd.read_csv(CSV_PATH)

need_cols = ["name", "exec_s", "exec_peak_mem_gb"]
missing = [c for c in need_cols if c not in df.columns]
if missing:
    raise ValueError(f"CSV missing columns: {missing}. Found: {list(df.columns)}")

# =========================
# 选两条线（不扩充点，只画真实存在的 k）
# =========================
df_bfs = df[df["name"].str.contains(r"^fattree-failure-ft-k\d+-fr0\.001-nodebfs", regex=True)]
df_nvwa = df[df["name"].str.contains(r"^fattree-failure-ft-k\d+-fr0\.001-rulebased", regex=True)]

# =========================
# 输出目录
# =========================
ensure_output_dir()

# =========================
# 1) Time 图（exec_s, 单位 s，log y）
# =========================
fig, ax = plt.subplots()
beautify_ax(ax)
apply_log_minor_ticks(ax)

k_n, y_n = prepare_series(df_nvwa, "exec_s")
k_b, y_b = prepare_series(df_bfs, "exec_s")

ax.plot(
    k_n, y_n,
    linestyle="-",
    linewidth=LINEWIDTH,
    color="C0",
    marker="o",
    markersize=MARKERSIZE,
    # markerfacecolor="none",
    markeredgewidth=2.0,
    label="Nüwa",
)
ax.plot(
    k_b, y_b,
    linestyle="--",
    dashes=(6, 4),
    linewidth=LINEWIDTH,
    color="C1",
    marker="s",
    markersize=MARKERSIZE,
    # markerfacecolor="none",
    markeredgewidth=2.0,
    label="BFS",
)

ax.set_xlabel("Fat-tree k")
ax.set_ylabel("Execution time (s)")
dedup_legend(ax, loc="upper left", fontsize=20)

fig.tight_layout()
out_time = output_path("failure-fattree-exec.pdf")
fig.savefig(out_time, bbox_inches="tight", dpi=300)
plt.close(fig)
print(f"Saved {out_time}")

# =========================
# 2) Memory 图（exec_peak_mem_gb, 单位 GB）
# =========================
fig, ax = plt.subplots()
beautify_ax(ax)

k_n, y_n = prepare_series(df_nvwa, "exec_peak_mem_gb")
k_b, y_b = prepare_series(df_bfs, "exec_peak_mem_gb")

ax.plot(
    k_n, y_n,
    linestyle="-",
    linewidth=LINEWIDTH,
    color="C0",
    marker="o",
    markersize=MARKERSIZE,
    # markerfacecolor="none",
    markeredgewidth=2.0,
    label="Nüwa",
)
ax.plot(
    k_b, y_b,
    linestyle="--",
    dashes=(6, 4),
    linewidth=LINEWIDTH,
    color="C1",
    marker="s",
    markersize=MARKERSIZE,
    # markerfacecolor="none",
    markeredgewidth=2.0,
    label="BFS",
)

ax.set_xlabel("Fat-tree k")
ax.set_ylabel("Peak memory (GB)")
dedup_legend(ax, loc="upper left", fontsize=20)

fig.tight_layout()
out_mem = output_path("failure-fattree-mem.pdf")
fig.savefig(out_mem, bbox_inches="tight", dpi=300)
plt.close(fig)
print(f"Saved {out_mem}")
