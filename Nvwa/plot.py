#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import re
from pathlib import Path
from matplotlib.ticker import LogLocator

plt.rcParams.update({
    "font.size": 26,
    "figure.figsize": (8,6),
    "axes.grid": True,
    "grid.linestyle": "--",
    "axes.labelsize": 28,   # 坐标轴标题字号
    "xtick.labelsize": 26,  # x 轴刻度字号
    "ytick.labelsize": 26,  # y 轴刻度字号
})

# -------- 文件列表 --------
Path("plots").mkdir(exist_ok=True)
csv_files = [
    "plots/fattree-time-mem.csv",
    "plots/dragonfly-time-mem.csv",
    "plots/torus-time-mem.csv",
]

# 读取并合并多个文件
dfs = []
for f in csv_files:
    df_tmp = pd.read_csv(f)
    df_tmp["source_file"] = f
    dfs.append(df_tmp)
df = pd.concat(dfs, ignore_index=True)

if "init_peak_mem_gb" not in df.columns and "init_mem_gb" in df.columns:
    df["init_peak_mem_gb"] = df["init_mem_gb"]
if "exec_peak_mem_gb" not in df.columns and "exec_mem_gb" in df.columns:
    df["exec_peak_mem_gb"] = df["exec_mem_gb"]

# 提取 Fat-tree k / Dragonfly h / Torus x
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
    if "fattree" in name: return "fattree"
    if "dragonfly" in name: return "dragonfly"
    if "torus" in name: return "torus"
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

# 样式映射
style_map = {
    "Nüwa":    {"fmt": "x-", "color": "C0"},
    "ns-3-dc": {"fmt": "s-", "color": "C1"},
    "ns-3":    {"fmt": "o-", "color": "C2"},
}

def plot_with_style(ax, x, y, system, label):
    ax.plot(
        x, y,
        style_map[system]["fmt"],
        color=style_map[system]["color"],
        linewidth=2,
        markersize=6,
        label=label
    )

def dedup_legend(ax, loc="best", **kwargs):
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc=loc, **kwargs)

def apply_log_minor_ticks(ax):
    ax.set_yscale("log")
    ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=np.arange(2,10)*0.1, numticks=10))

def apply_param_xticks(ax, df_sub, topo):
    xticks = sorted(df_sub["param"].dropna().unique())
    if topo == "fattree":
        labels = [f"FT{k}" for k in xticks]
    elif topo == "dragonfly":
        labels = [f"DF{h}" for h in xticks]
    elif topo == "torus":
        labels = [f"TR{x}" for x in xticks]
    else:
        labels = xticks
    ax.set_xticks(xticks)
    ax.set_xticklabels(labels, rotation=45, ha="right")

# -------- 通用绘图函数 --------
def plot_metric(df_sub, topo, metric, ylabel, filename, logy=True, kind="line"):
    if metric not in df_sub.columns:
        print(f"Skip {filename}: missing column {metric}")
        return

    fig, ax = plt.subplots()

    # 限制 Fat-tree 的 Execution time 只绘制到 k=64
    if topo == "fattree" and metric == "exec_s":
        df_sub = df_sub[df_sub["param"] <= 64]

    if logy:
        apply_log_minor_ticks(ax)

    xticks = sorted(df_sub["param"].dropna().unique())
    x = np.arange(len(xticks))
    bar_width = 0.25

    if kind == "bar":
        # 柱状图
        for i, sys in enumerate(["Nüwa", "ns-3-dc", "ns-3"]):
            dfs = df_sub[df_sub["routing"] == sys]
            if len(dfs) > 0:
                ax.bar(
                    x + (i - 1) * bar_width,
                    [dfs[dfs["param"] == k][metric].mean() for k in xticks],
                    width=bar_width,
                    label=sys,
                )
        ax.set_xticks(x)
        ax.set_xticklabels([f"FT{k}" if topo == "fattree" else
                            f"DF{k}" if topo == "Dragonfly" else
                            f"TR{k}" for k in xticks],
                           rotation=45, ha="right")
    else:
        # 折线图：使用类别型横坐标，保证等间距
        xticks = sorted(df_sub["param"].dropna().unique())
        x = np.arange(len(xticks))  # 等间距位置

        for sys in ["Nüwa", "ns-3-dc", "ns-3"]:
            dfs = df_sub[df_sub["routing"] == sys]
            if len(dfs) > 0:
                y = [dfs[dfs["param"] == k][metric].mean() for k in xticks]
                ax.plot(
                    x, y,
                    style_map[sys]["fmt"],
                    color=style_map[sys]["color"],
                    linewidth=2,
                    markersize=6,
                    label=sys
                )

        # 设置等间距刻度标签
        if topo == "fattree":
            labels = [f"FT{k}" for k in xticks]
        elif topo == "dragonfly":
            labels = [f"DF{h}" for h in xticks]
        elif topo == "torus":
            labels = [f"TR{x}" for x in xticks]
        else:
            labels = xticks
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        
    # ax.set_xlabel(f"{topo} size")
    ax.set_ylabel(ylabel)
    dedup_legend(ax, loc="best")
    fig.tight_layout()
    fig.savefig(filename, bbox_inches="tight")
    print(f"Saved {filename}")

def plot_memory_phase(df_sub, topo, filename):
    if "init_peak_mem_gb" not in df_sub.columns or "exec_peak_mem_gb" not in df_sub.columns:
        print(f"Skip {filename}: missing init/exec memory columns")
        return

    fig, ax = plt.subplots()
    xticks = sorted(df_sub["param"].dropna().unique())
    x = np.arange(len(xticks))

    for sys in ["Nüwa", "ns-3-dc", "ns-3"]:
        dfs = df_sub[df_sub["routing"] == sys]
        if len(dfs) == 0:
            continue
        init_y = [dfs[dfs["param"] == k]["init_peak_mem_gb"].mean() for k in xticks]
        exec_y = [dfs[dfs["param"] == k]["exec_peak_mem_gb"].mean() for k in xticks]
        ax.plot(
            x, init_y,
            style_map[sys]["fmt"],
            color=style_map[sys]["color"],
            linewidth=2,
            markersize=6,
            label=f"{sys} init",
        )
        ax.plot(
            x, exec_y,
            style_map[sys]["fmt"].replace("-", "--"),
            color=style_map[sys]["color"],
            linewidth=2,
            markersize=6,
            label=f"{sys} exec",
        )

    if topo == "fattree":
        labels = [f"FT{k}" for k in xticks]
    elif topo == "dragonfly":
        labels = [f"DF{h}" for h in xticks]
    elif topo == "torus":
        labels = [f"TR{x}" for x in xticks]
    else:
        labels = xticks
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Peak memory (GB)")
    dedup_legend(ax, loc="best", fontsize=18)
    fig.tight_layout()
    fig.savefig(filename, bbox_inches="tight")
    print(f"Saved {filename}")

# -------- 分拓扑绘图 --------
for topo in ["fattree", "dragonfly", "torus"]:
    df_sub = df[df["topology"] == topo]

    if len(df_sub) == 0:
        continue

        # Initialization time -> 柱状图
    plot_metric(df_sub, topo, "init_s", "Initialization time (s)", f"plots/init_{topo}.pdf", logy=True, kind="bar")

    # Execution time -> 折线图
    plot_metric(df_sub, topo, "exec_s", "Execution time (s)", f"plots/exec_{topo}.pdf", logy=False)

    # Execution memory
    plot_metric(df_sub, topo, "exec_peak_mem_gb", "Execution memory (GB)", f"plots/mem_{topo}.pdf", logy=False)

    # Initialization vs execution memory
    plot_memory_phase(df_sub, topo, f"plots/mem_phase_{topo}.pdf")

    # Total simulation time
    plot_metric(df_sub, topo, "wall_s", "Total simulation time (s)", f"plots/total_{topo}.pdf", logy=True)
