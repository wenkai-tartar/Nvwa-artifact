# Datacenter 模块示例

该目录包含 datacenter 模块的 C++ 示例、辅助输入文件以及验证脚本，可帮助快速搭建并测试不同的结构化数据中心拓扑。

## 目录结构

- `clos.cc`：手动构造 Clos 拓扑并运行简单的 UDP Echo 应用。
- `fattree.cc`：手动构造 Fat-Tree 拓扑并输出详细的节点/端口信息。
- `constructor.cc`：基于 JSON 配置自动生成拓扑，支持 `RuleBased`、`NodeBfs`、`NodeBfsWithHost`、`Global` 多种路由算法，并在 `--debug=1` 时生成 packet/flow trace。
- `dragonfly.cc`：直接构建 Dragonfly 拓扑，支持 `DragonflyValiantRouting` / `DragonflyUgalRouting`，可注入流量并输出 packet/flow trace。
- `constructor_fail.cc`：在 `constructor.cc` 基础上增加链路失效（Failure）支持，可通过 `--failure` 参数指定 JSON 格式的失效事件配置文件。
- `inputs/`：存放 JSON 拓扑描述以及 `topology_generator.py`。通过 `python3 inputs/topology_generator.py fattree --k 4`、`python3 inputs/topology_generator.py dragonfly --groups 9 --routers 4 --hosts 2 --global-links 2` 等命令生成配置文件。
- `inputs/failures/`：存放链路失效配置文件（JSON 格式），用于 `constructor_fail` 示例。
- `traces/`：示例运行时输出的 packet/flow trace 默认保存位置，便于调试与回归比对。
- `compare_constructor_traces.py`：辅助脚本，用于比较 constructor 示例在不同路由算法下生成的 packet trace 是否一致。

## 常用命令

1. 生成拓扑描述：
   ```bash
   python3 src/datacenter/examples/inputs/topology_generator.py fattree --k 4
   python3 src/datacenter/examples/inputs/topology_generator.py dragonfly --groups 9 --routers 4 --hosts 2 --global-links 2
   # 指定 dragonfly 全局连线策略（Absolute 或 SameRank）
   python3 src/datacenter/examples/inputs/topology_generator.py dragonfly --groups 9 --routers 4 --hosts 2 --global-links 2 --dragonfly-strategy SameRank
   # 生成包含 nonMinimal 配置的 JSON
   python3 src/datacenter/examples/inputs/topology_generator.py fattree --k 4 \
     --nonminimal --nonminimal-algorithm Valiant --nonminimal-metric bytes --nonminimal-transit-fields 0
   # 生成包含 nonMinimal 配置的 Dragonfly JSON
   python3 src/datacenter/examples/inputs/topology_generator.py dragonfly --groups 9 --routers 4 --hosts 2 --global-links 2 \
     --nonminimal --nonminimal-algorithm Valiant --nonminimal-metric bytes --nonminimal-transit-fields 0
   # 生成 100Gbps/1us Fat Tree（输出：fattree_k*_100g_1u.json）
   python3 src/datacenter/examples/inputs/topology_generator.py fattree --k 16 \
     --bandwidth 100Gbps --delay 1us
   # 生成 Torus 拓扑（custom 模式；TorusIntraLevel 的 LinkArrangement 注意大小写）
   # 例：2D torus(2x2)，直接让主机路由（无额外路由层）
   python3 src/datacenter/examples/inputs/topology_generator.py custom -o torus_2x2.json \
     --levels '[{"dims":[{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":2,"LinkArrangement":"SameRank"},{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":2,"LinkArrangement":"SameRank"}]}]'

   ```

2. 开启日志：
   ```bash
   export NS_LOG="FailureHelper=level_info|prefix_time:RuleBasedRouting=level_info|prefix_time"
   export NS_LOG_LEVEL=info
   ```

3. 运行示例（ constructor）：
   ```bash
   ./ns3 configure --build-profile=optimized --disable-tests --enable-examples --enable-modules "core;network;internet;applications;datacenter;point-to-point;nix-vector-routing"
   ./ns3 build
   ./ns3 run "constructor --config=fattree_k4.json --routing=RuleBased"
   ```

   内存泄漏 debug:
   ```bash
   ./ns3 configure '--build-profile=debug' --enable-modules "core;network;internet;applications;datacenter;point-to-point;nix-vector-routing" --enable-examples --enable-sanitizers
   ```

4. 运行带链路失效的示例（constructor）：
   ```bash
   # 使用绝对路径
   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_all_tor_agg.json --debug=true"
   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_1_tor_agg_1_agg_core.json --debug=true"
   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_1_tor_agg_2_agg_core.json --debug=true"

   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_all_tor_agg.json --routing=NodeBfs --debug=true"
   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_1_tor_agg_1_agg_core.json --routing=NodeBfs --debug=true"
   ./ns3 run "constructor --config=fattree_k4.json --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_1_tor_agg_2_agg_core.json --routing=NodeBfs --debug=true"

   # 或使用相对路径（自动在 inputs/failures/ 目录下查找）
   ./ns3 run "constructor --config=fattree_k4.json --failure=fattree_k4_example.json --debug=true"
   ```
   - 按链路比例随机注入 failure（例如 0.01%）：
     ```bash
     ./ns3 run "constructor --config=fattree_k4.json --routing=RuleBased --debug=1 \
       --randomFailureRate=0.0001 --randomFailureTime=0.5 --randomFailureTimeUnit=s --randomFailureSeed=1"
     ```
     ```bash
     ./ns3 run "constructor --config=fattree_k8.json --routing=RuleBased --debug=1 \
    --randomFailureRate=0.1 --randomFailureTime=0.5 --randomFailureTimeUnit=s --randomFailureSeed=1 \
    --randomFailureOut=random_failures_seed1.json"
     ```
     - 说明：随机 failure 可与 `--failure` 叠加；trace 文件名不包含随机参数，重复运行会覆盖。

4.1 Failure / Non-minimal 批量实验与单用例脚本：

   详见：`src/datacenter/experiments/README.md`

5. 比较不同路由算法的 packet trace：
   ```bash
   python3 src/datacenter/examples/compare_constructor_traces.py --config=fattree_k4.json
   ```

5. 比较 failure 场景下的 packet trace（推荐用于 RuleBased vs NodeBfsStrict）：
   ```bash
   python3 src/datacenter/examples/compare_constructor_packet_traces.py \
     --config=fattree_k4.json \
     --failure=src/datacenter/examples/inputs/failures/fattree_k4_failure_1_tor_agg_2_agg_core.json
   ```
   ```bash
   python3 src/datacenter/examples/compare_constructor_packet_traces.py \
     --config=fattree_k4.json \
     --failure=src/datacenter/examples/inputs/failures/random_failures_seed1.json
   ```
   - 只比较已有 trace（不重新运行仿真）：加 `--skip-run`
   - 只比较 failure 后时间窗口：加 `--time-from=<seconds>`
   - 随机 failure 对比（脚本会自动跑两遍并传入随机参数）：
     ```bash
     python3 src/datacenter/examples/compare_constructor_packet_traces.py \
       --config=fattree_k4.json \
       --randomFailureRate=0.0001 --randomFailureTime=0.5 --randomFailureTimeUnit=s --randomFailureSeed=1
     ```

     ```bash
     python3 src/datacenter/examples/compare_constructor_packet_traces.py \
       --config=fattree_k4.json \
       --randomFailureRate=0.0001 --randomFailureTime=0.5 --randomFailureTimeUnit=s --randomFailureSeed=1
     ```

6. 运行 Non-minimal（Valiant）示例：
   ```bash
   ./ns3 run "constructor --config=fattree_k4_valiant.json --routing=RuleBased --trafficPattern=flows --numFlows=2 --flowSize=262144 --debug=1"
   ```

7. 运行 Non-minimal（UGAL）示例：
   ```bash
   # 先生成包含 UGAL 配置的 JSON（输出：fattree_ugal_k4.json）
   python3 src/datacenter/examples/inputs/topology_generator.py fattree --k 4 -o fattree_ugal.json \
     --nonminimal --nonminimal-algorithm UGAL --nonminimal-metric bytes \
     --nonminimal-alpha 1.0 --nonminimal-detour-penalty 1.0 --nonminimal-transit-fields 0

   ./ns3 run "constructor --config=fattree_ugal_k4.json --routing=RuleBased --trafficPattern=flows --numFlows=2 --flowSize=262144 --debug=1"

   ./ns3 run "constructor --config=fattree_ugal_k4.json --routing=RuleBased --debug=1"
   ```

8. 运行 Torus 示例：
   ```bash
   # 使用 custom 生成的 torus JSON
   ./ns3 run "constructor --config=torus_2x2.json --routing=RuleBased --debug=1"
   ```

9. 运行 Torus Detour 示例（Non-minimal）：
   ```bash
   # 生成带 Detour 配置的 torus JSON（按 flowHash 做 dst 偏移，多阶段）
   python3 src/datacenter/examples/inputs/topology_generator.py custom -o torus_2x2_detour.json \
     --levels '[{"dims":[{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":2,"LinkArrangement":"SameRank"},{"template":"TorusIntraLevel","nodeNum":0,"subBlockNum":2,"LinkArrangement":"SameRank"}]}]' \
     --nonminimal --nonminimal-algorithm Detour --nonminimal-transit-fields 0,1 --nonminimal-detour-stages 2

   ./ns3 run "constructor --config=torus_2x2_detour.json --routing=RuleBased --debug=1"
   ```

9.1 Non-minimal 批量实验脚本：

   详见：`src/datacenter/experiments/README.md`

10. 运行 Dragonfly 示例（Valiant + traffic + trace）：
   ```bash
   ./ns3 run "dragonfly --groups=9 --routersPerGroup=4 --hostsPerRouter=2 --globalLinksPerRouter=2 --seed=1 --trafficPattern=flows --numFlows=4 --flowSize=262144 --debug=1 --tracePrefix=dragonfly_valiant"

   ./ns3 run "dragonfly --groups=5 --routersPerGroup=2 --hostsPerRouter=2 --globalLinksPerRouter=2 --seed=0 --dumpCaches=1 --trafficPattern=flows --numFlows=1 --flowSize=100 --debug=1 --tracePrefix=dragonfly_valiant"
   ```

11. 运行 Dragonfly 示例（UGAL baseline）：
   ```bash
   ./ns3 run "dragonfly --routing=ugal --groups=5 --routersPerGroup=2 --hostsPerRouter=2 --globalLinksPerRouter=2 \
     --seed=1 --ugalAlpha=1.0 --ugalDetourPenalty=1.0 --ugalMetric=bytes \
     --debug=1 --tracePrefix=dragonfly_ugal"
   ```

12. 比较 RuleBasedRouting 的 Valiant 策略与 DragonflyValiantRouting 的 packet trace：
   ```bash
   # 1) 生成带 non-minimal 配置的 dragonfly JSON（RuleBased 使用）
   python3 src/datacenter/examples/inputs/topology_generator.py dragonfly \
     --groups 5 --routers 2 --hosts 2 --global-links 2 \
     --nonminimal --nonminimal-algorithm Valiant --nonminimal-metric bytes --nonminimal-transit-fields 2

   # 2) RuleBasedRouting（Valiant）跑 constructor
   ./ns3 run "constructor --config=dragonfly_g5_a2_p2_h2.json --routing=RuleBased --debug=1"

   # 3) DragonflyValiantRouting（DVR）跑 dragonfly
   ./ns3 run "dragonfly --groups=5 --routersPerGroup=2 --hostsPerRouter=2 --globalLinksPerRouter=2 \
     --seed=0 --debug=1 --tracePrefix=dragonfly_dvr"

   # 4) 比较 packet trace（去掉注释行）
   grep -v '^#' src/datacenter/examples/traces/dragonfly_g5_a2_p2_h2_RuleBased_packet_trace.txt > /tmp/rb.txt
   grep -v '^#' src/datacenter/examples/traces/dragonfly_dvr_packet_trace.txt > /tmp/dvr.txt
   diff -u /tmp/rb.txt /tmp/dvr.txt
   ```

13. 比较 RuleBasedRouting 的 UGAL 策略与 DragonflyUgalRouting 的 packet trace：
   ```bash
   # 1) 生成带 non-minimal（UGAL）配置的 dragonfly JSON（RuleBased 使用）
   python3 src/datacenter/examples/inputs/topology_generator.py dragonfly \
     --groups 5 --routers 2 --hosts 2 --global-links 2 \
     --nonminimal --nonminimal-algorithm UGAL --nonminimal-metric bytes \
     --nonminimal-alpha 1.0 --nonminimal-detour-penalty 1.0 --nonminimal-transit-fields 2

   # 2) RuleBasedRouting（UGAL）跑 constructor
   ./ns3 run "constructor --config=dragonfly_g5_a2_p2_h2.json --routing=RuleBased --debug=1"

   # 3) DragonflyUgalRouting（DUR）跑 dragonfly
   ./ns3 run "dragonfly --routing=ugal --groups=5 --routersPerGroup=2 --hostsPerRouter=2 \
     --globalLinksPerRouter=2 --seed=0 --ugalAlpha=1.0 --ugalDetourPenalty=1.0 --ugalMetric=bytes \
     --debug=1 --tracePrefix=dragonfly_dur"

   # 4) 比较 packet trace（去掉注释行）
   grep -v '^#' src/datacenter/examples/traces/dragonfly_g5_a2_p2_h2_RuleBased_packet_trace.txt > /tmp/rb.txt
   grep -v '^#' src/datacenter/examples/traces/dragonfly_dur_packet_trace.txt > /tmp/dur.txt
   diff -u /tmp/rb.txt /tmp/dur.txt
   ```

14. 获取帮助：
   ```bash
   ./ns3 run constructor -- --help
   ./ns3 run constructor_fail -- --help
   ```

## 注意事项

- 所有命令默认在仓库根目录执行，示例会自动在 `build/` 目录下生成可执行文件。
- constructor 示例若要输出 trace，请加上 `--debug=1`，并检查 `src/datacenter/examples/traces` 是否存在写权限。
- dragonfly 示例若要输出 trace，请加上 `--debug=1`，并用 `--tracePrefix` 指定文件前缀。
- 若需自定义拓扑，可编辑 `inputs/*.json` 或通过 `topology_generator.py custom --levels <JSON>` 传入自定义层级配置。
- **非最短路由配置**（仅 `RuleBased` 有效）：
  ```json
  {
    "nonMinimal": {
      "enable": true,
      "algorithm": "Valiant",  // 或 "UGAL" / "Detour"
      "metric": "bytes",       // bytes | packets | none
      "alpha": 1.0,            // 仅 UGAL 使用
      "detourPenalty": 1.0,    // 仅 UGAL 使用
      "detourStages": 2,       // 仅 Detour 使用（多阶段）
      "transitFields": [0, 1]  // 可选：StructuredAddress 中要重写/偏移的字段索引
    }
  }
  ```
  - 说明：Valiant 选择 transit 时会同时避免选择与 src/dst 相同的字段值（若可选集合允许）。
  - Detour 策略：基于 dst 在指定字段上做“偏移”，偏移量由 flowHash 选择，默认只在 inject 阶段选一次。
- **链路失效配置格式**（`inputs/failures/*.json`）：
  ```json
  {
    "failures": [
      {
        "link": {
          "src": {"level": 1, "local_index": 0},
          "dst": {"level": 2, "local_index": 0}
        },
        "failure_time": 5.0,
        "failure_time_unit": "s",
        "recovery_time": 15.0,
        "recovery_time_unit": "s"
      }
    ]
  }
  ```
  - `level` 和 `local_index` 用于指定层级结构中的节点位置
  - 时间单位支持：`s`（秒）、`ms`（毫秒）、`us`（微秒）、`ns`（纳秒）
  - `recovery_time` 为可选项，若不指定则链路永久失效
  - 链路失效总是双向的，会同时影响两个方向的接口
