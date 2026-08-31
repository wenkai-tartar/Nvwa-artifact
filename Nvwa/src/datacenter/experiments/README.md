# Experiments（Datacenter）

本目录包含可复现实验的脚本与命令示例。以下命令均在仓库根目录执行：

```bash
cd /workspace/Nvwa
```

默认参数说明：
- 大多数实验脚本默认 `--trafficPattern allreduce`；`nonminimal_sweep.py` 默认
  `--trafficPattern grouped-allreduce`
- 默认 `--flowSize 1048576` / `--dataSize 1048576`（1MB）
- 若未显式指定 `--out` / `--log-dir`，默认输出文件名格式为：  
  `<function>-<topology>-<routing>-<traffic>-<sizeKB>KB.csv`  
  其中 `sizeKB = flowSize / 1024`（1MB = 1024KB）。多拓扑时使用 `Dragonfly-Torus`。

## 1) 正确性验证（RuleBased vs baseline）

脚本：`src/datacenter/experiments/correctness_check.py`

会自动生成/覆盖 trace：`src/datacenter/examples/traces/`  
失败时输出 diff：`results/correctness/diffs/`  
每条命令的运行日志：`results/correctness/logs/`

### 1.1 先编译一次（必须）

```bash
./ns3 configure --build-profile=optimized --disable-tests --enable-examples --enable-modules "core;network;internet;applications;datacenter;point-to-point;nix-vector-routing"
./ns3 build
```

### 1.2 Failure 正确性（NodeBfsStrict baseline）

验证内容：
- Fattree：k = 8, 16, 24, 32
- failure rate：0.001, 0.01, 0.1
- 对比：`NodeBfsStrict` vs `RuleBased`（同一份 failure JSON）

```bash
python3 src/datacenter/experiments/correctness_check.py failure
```

只跑子集（smoke）：

```bash
python3 src/datacenter/experiments/correctness_check.py failure --k 8,16 --rates 0.001
```

### 1.3 Non-minimal 正确性（baseline vs RuleBased policy）

验证内容：
- **Dragonfly**：h = 2, 4, 6  
  baseline：`DragonflyValiantRouting` / `DragonflyUgalRouting`（`dragonfly` 示例）  
  对比：`constructor` 的 RuleBased non-minimal（JSON 配置）
- **Torus**：d = 5, 10, 15（3D：`d^3` 节点），stages = 1 / 2  
  baseline：`TorusDetourRouting`（`torus_detour` 示例）  
  对比：`constructor` 的 RuleBased Detour policy（JSON 配置）

```bash
python3 src/datacenter/experiments/correctness_check.py nonminimal
```

分开执行（按策略拆分）：

```bash
python3 src/datacenter/experiments/correctness_check.py nonminimal-dragonfly-valiant
python3 src/datacenter/experiments/correctness_check.py nonminimal-dragonfly-ugal
python3 src/datacenter/experiments/correctness_check.py nonminimal-torus-detour
```

只跑子集（全量 nonminimal）：

```bash
python3 src/datacenter/experiments/correctness_check.py nonminimal --h 2 --d 5 --torus-stages 1
```

只跑子集（拆分指令）：

```bash
python3 src/datacenter/experiments/correctness_check.py nonminimal-dragonfly-valiant --h 2
python3 src/datacenter/experiments/correctness_check.py nonminimal-dragonfly-ugal --h 2
python3 src/datacenter/experiments/correctness_check.py nonminimal-torus-detour --d 5 --torus-stages 1
```

### 1.4 结果判定

- 退出码 0：全部一致  
- 退出码 2：存在不一致或运行失败  
  - diff：`results/correctness/diffs/*.diff`  
  - 日志：`results/correctness/logs/*.log`

---

## 2) Non-minimal 策略性能实验（RuleBased）

脚本：`src/datacenter/experiments/nonminimal_sweep.py`  
拆分脚本：  
- `src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py`  
- `src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py`  
- `src/datacenter/experiments/nonminimal_sweep_torus_detour.py`

实验规模：
1. Dragonfly Valiant：h = 2, 4, 6, 8, 10  
2. Dragonfly UGAL：h = 2, 4, 6, 8, 10  
3. 3D Torus Detour（1 阶段）：d = 5, 10, 15, 20  
4. 3D Torus Detour（2 阶段）：d = 5, 10, 15, 20  

配置说明：
- Dragonfly full-size：`a = 2p = 2h, g = a*h + 1`
- Torus：三维均为 d，节点数 `d*d*d`
流量模式：
- `flows`：使用 `--numFlows/--flowSize`
- `allreduce` / `grouped-allreduce` / `alltoall`：`nonminimal_sweep.py` 自动设置
  `degree=4/4/8`
- `grouped-allreduce` 默认使用 group size 8、strided placement、step gap 0

### 2.1 分开 sweep（Dragonfly / Torus）

```bash
python3 src/datacenter/experiments/nonminimal_sweep.py \
  --skip-build \
  --build-profile optimized \
  --max-retries 3 \
  --only dragonfly_valiant,dragonfly_ugal

python3 src/datacenter/experiments/nonminimal_sweep.py \
  --skip-build \
  --build-profile optimized \
  --max-retries 3 \
  --only torus_detour1,torus_detour2
```

### 2.2 只跑 Dragonfly / Torus

```bash
python3 src/datacenter/experiments/nonminimal_sweep.py \
  --skip-build \
  --only dragonfly_valiant,dragonfly_ugal
```

```bash
python3 src/datacenter/experiments/nonminimal_sweep.py \
  --skip-build \
  --only torus_detour1,torus_detour2
```

等价的拆分脚本：

```bash
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_torus_detour.py --skip-build
```

### 2.3 只跑部分 h / d

```bash
python3 src/datacenter/experiments/nonminimal_sweep.py \
  --skip-build \
  --only-h 2,4 \
  --only-d 5,10
```

### 2.4 CSV 在哪 / 怎么看

```bash
ls -lh plots/nonminimal-*.csv
tail -n 10 plots/nonminimal-*.csv
```

---

## 3) Failure 性能实验（RuleBased）

脚本：`src/datacenter/experiments/fattree_failure_sweep.py`

实验规模：
- Fattree size：k = 8, 16, 24, 32, 40, 48, 56, 64
- failure rate：0.001, 0.01, 0.1

### 3.1 全量 sweep

```bash
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --resume-policy skip_success
```

### 3.2 只跑子集（例如 K=8,16；fr=0.001,0.01）

```bash
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --only-k 8,16,24 \
  --only-fr 0.001,0.01 \
  --resume-policy skip_success
```

### 3.3 CSV 在哪 / 怎么看

```bash
ls -lh plots/failure-Fattree-*.csv
tail -n 10 plots/failure-Fattree-*.csv
```

---

## 4) 最短路性能实验基线（NodeBfs / RuleBased）

### 4.1 Fattree

脚本：`src/datacenter/experiments/fattree_shortest_sweep.py`

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

### 4.2 Dragonfly 最短路基线

脚本：`src/datacenter/experiments/dragonfly_shortest_sweep.py`

运行前测试：

```bash
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-h 2

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-h 2
```

实验命令：

```bash
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

> 默认参数：dragonfly h = 2,4,6,8,10  
> 可用 `--only-h` 覆盖

### 4.3 3D Torus 最短路基线

脚本：`src/datacenter/experiments/torus_shortest_sweep.py`

运行前测试：

```bash
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-d 2

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-d 2
```

实验命令：

```bash
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

> 默认参数：3D torus d = 5,10,15,20  
> 可用 `--only-d` 覆盖

---

## 5) 初始化阶段 Memory Profiling（FatTree k-scaling）

脚本：`src/datacenter/experiments/fattree_memory_profile_sweep.py`

用途：
- 固定同一种 FatTree topology family，系统性改变 `k`
- 自动生成 JSON config 到本次 run 的 `configs/`
- 每个 case 使用 `constructor --memory=true`
- 保存原始日志、manifest、summary、初始化阶段 memory profile、对象规模 profile

FatTree size 指定：
- 通过 `--k-values 4,8,12,16` 指定一组 k-ary FatTree，`k` 必须是正偶数
- 对每个 `k`，脚本按 `topology_generator.py` 的 FatTree 规则生成拓扑：
  - 每个 edge switch 连接 `k/2` hosts
  - 一共有 `k` 个 pods
  - 每个 pod 有 `k/2` edge switches 和 `k/2` aggregation switches
  - core 层有 `(k/2)^2` switches
  - host 数为 `k^3/4`
- 生成的具体拓扑 JSON 会保存在本次 run 的 `configs/fattree_k*.json`

### 5.1 Smoke test

```bash
python3 src/datacenter/experiments/fattree_memory_profile_sweep.py \
  --skip-build \
  --k-values 4 \
  --routings NodeBfs \
  --repeats 1
```

### 5.2 NodeBfs scaling

```bash
python3 src/datacenter/experiments/fattree_memory_profile_sweep.py \
  --skip-build \
  --k-values 4,8,12,16 \
  --routings NodeBfs \
  --repeats 3
```

### 5.3 和 RuleBased/Global 对比

```bash
python3 src/datacenter/experiments/fattree_memory_profile_sweep.py \
  --skip-build \
  --k-values 4,8,12,16 \
  --routings NodeBfs,RuleBased,Global \
  --repeats 3
```

### 5.4 输出

默认输出目录：

```bash
results/fattree-memory-profile-YYYYmmdd-HHMMSS/
```

关键文件：
- `manifest.json`：git SHA、dirty 状态、命令行、k values、routing、repeat 等复现实验元数据
- `experiment_2_summary.csv`：每次 run 的 `init_peak_mem`、`exec_peak_mem`、`routing_state_delta/share`、`routing_entries`
- `experiment_2_memory_profile.csv`：初始化阶段逐阶段 RSS 增量和占比
- `experiment_2_object_profile.csv`：各阶段 nodes、netdevices、channels、routing entries、applications 等对象规模
- `logs/*.log`：每次 run 的原始 stdout

### 5.5 绘图

脚本：`src/datacenter/experiments/plot_fattree_memory_profile.py`

直接绘制最新一次 run：

```bash
python3 src/datacenter/experiments/plot_fattree_memory_profile.py
```

指定 run 目录：

```bash
python3 src/datacenter/experiments/plot_fattree_memory_profile.py \
  --run-dir results/fattree-memory-profile-YYYYmmdd-HHMMSS \
  --formats pdf,png
```

默认输出：

```bash
results/fattree-memory-profile-YYYYmmdd-HHMMSS/figures/
```

主要图：
- `routing_state_share.pdf`：`routing_state` 在初始化内存增量中的占比
- `routing_state_delta.pdf`：`routing_state` RSS 增量
- `init_peak_memory.pdf` / `exec_peak_memory.pdf`
- `routing_entries.pdf`
- `routing_comparison_stage_share.pdf`：每个 FatTree `k` 一组，组内比较 Global / NodeBfs / RuleBased 的 Topology / Routing state / Other share
- `stage_breakdown_<routing>_delta.pdf`
- `stage_breakdown_<routing>_share.pdf`：Topology / Routing state / Other 三段 stacked share

---

## 6) 初始化阶段 Time Profiling（FatTree k-scaling）

脚本：`src/datacenter/experiments/fattree_time_profile_sweep.py`

用途：
- 和 memory profiling sweep 使用同样的 FatTree config 生成方式、manifest、logs 和 CSV 输出结构
- 每个 case 使用 `constructor --timeProfile=true`
- 默认使用 `--initOnly=true`，只测初始化阶段，不进入 `Simulator::Run`
- 默认使用 `--memory=false`，避免 memory profiler 和对象统计影响初始化耗时

### 6.1 Smoke test

```bash
python3 src/datacenter/experiments/fattree_time_profile_sweep.py \
  --skip-build \
  --k-values 4 \
  --routings RuleBased,NodeBfs \
  --repeats 1
```

### 6.2 RuleBased 和 NodeBfs scaling

```bash
python3 src/datacenter/experiments/fattree_time_profile_sweep.py \
  --skip-build \
  --k-values 4,6,8,10,12,14,16 \
  --routings RuleBased,NodeBfs \
  --repeats 3
```

如需同时跑仿真执行阶段，添加 `--run-simulation`；如需同时输出 memory profile，添加 `--memory-profile`。

### 6.3 输出

默认输出目录：

```bash
results/fattree-time-profile-YYYYmmdd-HHMMSS/
```

关键文件：
- `manifest.json`：git SHA、dirty 状态、命令行、k values、routing、repeat 等复现实验元数据
- `experiment_3_summary.csv`：每次 run 的总初始化时间、拓扑构建时间、路由计算时间、其他时间和占比
- `experiment_3_time_profile.csv`：初始化阶段逐阶段耗时和占比
- `experiment_3_time_breakdown.csv`：Topology / Routing computation / Other 三段汇总，便于直接画 stacked breakdown
- `logs/*.log`：每次 run 的原始 stdout

`experiment_3_time_profile.csv` 中的 `accounted` 字段用于区分父阶段和细粒度明细：
- `accounted=yes` 行参与 `accounted_s/other_s` 汇总，可直接用于 stacked breakdown
- `accounted=no` 行是 nested detail，不重复计入总时间；其中 NodeBfs 会额外输出 `routing_node_bfs_bfs`、`routing_node_bfs_install_entries`、`routing_node_bfs_clear_tables`、`routing_node_bfs_count_entries` 等阶段，以及 `node_visits`、`edge_scans`、`next_hop_records`、`entries` 等计数，用于解释初始化慢点来自 BFS 遍历还是 routing-table materialization

---

## 7) Dragonfly 真实 Trace Replay

脚本：`src/datacenter/experiments/dragonfly_trace_sweep.py`

用途：
- 自动扫描 Nvwa trace CSV 的 `src/dst` rank 范围
- `--h-values auto` 会选择最小 `h >= 2` 的 full-size Dragonfly，使 host 数覆盖 trace rank
- 自动生成本次 run 的 Dragonfly JSON 到 `configs/`
- 对同一个拓扑和同一个 trace 比较 `RuleBased` 与 `NodeBfs`
- 保存 `manifest.json`、`experiment_6.csv`、`logs/*.log`

映射假设：trace CSV 是 rank-level 流量，脚本使用 `rank i -> Dragonfly host index i`。脚本会验证 host 数足够，但 CSV 本身不包含原始 group/router/local-host placement 元数据。

### 7.1 Grok N512 50-per-rank

```bash
python3 src/datacenter/experiments/dragonfly_trace_sweep.py \
  --skip-build \
  --h-values auto \
  --routings RuleBased,NodeBfs \
  --traffic-trace /data/wkli/grok314b_n512/grok_n512.50perrank.nvwa.csv \
  --traffic-trace-max-flows 0 \
  --packet-size 64000 \
  --out-dir results/dragonfly_grok_n512_hauto_50perrank_pkt64k
```

Grok N512 trace 覆盖 ranks `0..2047`，因此 `auto` 会选择 `h=5`：`g=51, a=10, p=5, hosts=2550`。

### 7.2 Grok N512 200-per-rank

```bash
python3 src/datacenter/experiments/dragonfly_trace_sweep.py \
  --skip-build \
  --h-values auto \
  --routings RuleBased,NodeBfs \
  --traffic-trace /data/wkli/grok314b_n512/grok_n512.200perrank.nvwa.csv \
  --traffic-trace-max-flows 0 \
  --packet-size 64000 \
  --out-dir results/dragonfly_grok_n512_hauto_200perrank_pkt64k
```

### 7.3 输出

关键字段：
- `h/g/a/p/dragonfly_hosts`：生成的 Dragonfly 拓扑规模
- `trace_required_hosts/trace_unique_ranks/trace_max_rank`：trace rank 覆盖验证
- `traffic_trace_flows`：实际 replay 的 flow 数
- `init_s/exec_s/wall_s`
- `init_peak_mem_kb/exec_peak_mem_kb`
- `rule_based_rules/routing_entries/forward_count`
