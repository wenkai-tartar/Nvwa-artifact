# ATLAHS Trace Traffic in Nvwa

This note records the bridge for replaying ATLAHS workloads through Nvwa's ns-3
datacenter backend.

## Scope

The current bridge converts an ATLAHS text `.goal` schedule into a Nvwa traffic
CSV. Each GOAL `send` becomes one ns-3 UDP flow:

```csv
start_s,src,dst,bytes,tag
```

For binary LogGOPSim schedules, the converter replays the serialized ATLAHS DAG
and writes each send at its LogGOPSim issue time. That preserves calc/send/recv
dependencies, start-dependencies, message arrival, receive matching, and
eager/rendezvous dependency release before ns-3 sees the trace.

The ns-3 run still replays the resulting send flows open-loop: packet completion
inside ns-3 is not fed back into the ATLAHS DAG. Treat this as a realistic
workload send-timing replay, not as a coupled ATLAHS+ns-3 training runtime.

## Convert GOAL to Nvwa CSV

```bash
python3 src/datacenter/experiments/atlahs_goal_to_nvwa_trace.py \
  -i /path/to/InterNode_MicroEvents_Dependency.goal \
  -o /path/to/workload.nvwa.csv \
  --host-count 16
```

For quick smoke tests on a smaller topology only, ranks can be mapped modulo the
available hosts:

```bash
python3 src/datacenter/experiments/atlahs_goal_to_nvwa_trace.py \
  -i /path/to/workload.goal \
  -o /path/to/workload.nvwa.csv \
  --host-count 16 \
  --map-modulo-hosts \
  --max-flows 1000
```

For large traces, use the streaming rank-order mode when the experiment only
needs real communication pairs and sizes:

```bash
python3 src/datacenter/experiments/atlahs_goal_to_nvwa_trace.py \
  -i /path/to/large.goal \
  -o /path/to/large.sample.nvwa.csv \
  --schedule-mode rank-order \
  --host-count 32 \
  --rank-sequence-gap-s 0.000001 \
  --max-flows 100000 \
  --stop-after-max-flows
```

`--schedule-mode dag` is the default and uses GOAL dependencies to estimate
relative start times. `--schedule-mode rank-order` ignores dependency edges and
assigns start times from each rank's local operation order, which is useful for
quick real-trace traffic-matrix experiments on very large GOAL files.

## Convert LogGOPSim Binary to Nvwa CSV

ATLAHS also publishes LogGOPSim `.bin` schedules. These are often smaller than
the text GOAL files and can be converted directly:

```bash
python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i /path/to/workload.bin \
  -o /path/to/workload.bin.nvwa.csv \
  --host-count 32
```

`--schedule-mode loggops` is the default. It replays the binary schedule with
LogGOPSim's default timing parameters:

- `--loggops-l 2500`
- `--loggops-o 1500`
- `--loggops-g 1000`
- `--loggops-G 6`
- `--loggops-S 65535`
- `--loggops-O 0`
- `--time-scale-s-per-unit 1e-9`

Use the same LogGOPS parameters as the ATLAHS/LogGOPSim run if the trace was
validated with non-default values.

For a balanced large-trace subset, take a fixed number of nonzero sends per
rank:

```bash
python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i /path/to/lammps_32.bin \
  -o /path/to/lammps_32.200perrank.nvwa.csv \
  --host-count 32 \
  --max-flows-per-rank 200
```

For a quick traffic-matrix smoke test only, use the legacy streaming mode:

```bash
python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i /path/to/workload.bin \
  -o /path/to/workload.rank_order.nvwa.csv \
  --schedule-mode rank-order \
  --host-count 32 \
  --rank-sequence-gap-s 0.000001 \
  --max-flows-per-rank 200
```

Do not use `rank-order` for the memory-bottleneck experiment. It ignores the
ATLAHS dependency graph and can collapse a realistic workload into an artificial
burst.

## Run One Nvwa Case

```bash
./ns3 build constructor

./build/src/datacenter/examples/ns3-dev-constructor-optimized \
  --config=fattree_k16_100g_1u.json \
  --routing=RuleBased \
  --trafficPattern=trace \
  --trafficReplayMode=batch \
  --trafficTrace=/path/to/workload.nvwa.csv \
  --packetSize=64000 \
  --trafficTraceStopPadding=10 \
  --memory=true
```

Run the same trace with a baseline routing implementation:

```bash
./build/src/datacenter/examples/ns3-dev-constructor-optimized \
  --config=fattree_k16_100g_1u.json \
  --routing=NodeBfs \
  --trafficPattern=trace \
  --trafficReplayMode=batch \
  --trafficTrace=/path/to/workload.nvwa.csv \
  --packetSize=64000 \
  --trafficTraceStopPadding=10 \
  --memory=true
```

## Run a Fattree Sweep

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 8,16,24,32 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace /path/to/workload.nvwa.csv \
  --packetSize 64000 \
  --out plots/fattree-atlahs-trace-time-mem.csv \
  --log-dir results/fattree-atlahs-trace-logs
```

Key metrics remain the existing Nvwa metrics: initialization time, execution
time, peak memory, routing entry count, and forwarding stats. The sweep CSV also
records `traffic_pattern`, `traffic_replay_mode`, `packet_size`,
`traffic_trace_flows`, `nodes`, `rule_based_rules`, `routing_entries`,
`applications`, and initialization/execution peak memory so real-trace runs can
be mapped directly to the paper's control-plane claims.

For full ATLAHS traces with many large flows, increasing `--packetSize` reduces
packet-level event count. For example, `--packetSize 64000` preserves flow byte
counts while avoiding millions of 1000-byte UDP packets.

## Server Runbook: Grok314B N256

Use this section on a server, not on a laptop. The Grok314B N256 trace is:

- Workload: `Grok314B_N256_GPU1024_TP4_PP1_CP1_VP1_EP8_ETP4_GBS2048`
- Ranks/GPUs: 1024
- Natural FatTree match: `k=16`, because a k-ary FatTree has `k^3 / 4` hosts
  and `16^3 / 4 = 1024`
- Binary trace URL:
  `http://storage2.spcl.ethz.ch/traces/ai/grok/Grok314B_N256_GPU1024_TP4_PP1_CP1_VP1_EP8_ETP4_GBS2048/grok.bin`
- Binary size: about 34.2 GiB / 36,732,921,464 bytes
- Text GOAL size: about 60 GiB

Prefer the `.bin` file. It is much smaller than `.goal` and is directly
supported by `atlahs_bin_to_nvwa_trace.py`.

### 1. Prepare a Server Workspace

Run the commands from the Nvwa repository root. Put the large trace under a
server scratch directory, not under the git checkout.

```bash
cd /path/to/Nvwa

SCRATCH=/path/to/scratch/nvwa-atlahs
GROK_DIR=$SCRATCH/grok314b_n256
mkdir -p "$GROK_DIR" plots results

./ns3 configure --build-profile=optimized --disable-tests --enable-examples \
  --enable-modules "core;network;internet;applications;datacenter;point-to-point;nix-vector-routing"
./ns3 build constructor -j "$(nproc)"
```

### 2. Download the Grok N256 Binary Trace

The download is resumable. Re-run the same command if it is interrupted.

```bash
GROK_BIN=$GROK_DIR/grok_n256.bin

curl -L --fail -C - \
  -o "$GROK_BIN" \
  http://storage2.spcl.ethz.ch/traces/ai/grok/Grok314B_N256_GPU1024_TP4_PP1_CP1_VP1_EP8_ETP4_GBS2048/grok.bin

ls -lh "$GROK_BIN"
```

Expected size is about `34G` in `ls -lh`. Exact HTTP `Content-Length` observed
from the server is `36732921464` bytes.

### 3. Convert a First Sample

Start with a balanced sample before attempting the full trace. This emits up to
200 nonzero sends per rank, so at most about 204,800 flows across 1024 ranks.
The binary converter advances the LogGOPSim event schedule until the sampled
sends are collected, then writes only those sampled flows to CSV.

```bash
GROK_SAMPLE_CSV=$GROK_DIR/grok_n256.200perrank.nvwa.csv

python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i "$GROK_BIN" \
  -o "$GROK_SAMPLE_CSV" \
  --host-count 1024 \
  --max-flows-per-rank 200 \
  --progress-interval 1000000

wc -l "$GROK_SAMPLE_CSV"
head -n 5 "$GROK_SAMPLE_CSV"
```

Use `--host-count 1024` without `--map-modulo-hosts`; Grok N256 naturally fits
FatTree k=16. Do not add `--rank-sequence-gap-s` in the default mode: the
converter now gets send times from the binary DAG and LogGOPSim event semantics,
not from synthetic node-offset spacing.

### 4. Run the k=16 RuleBased vs NodeBfs Comparison

This is the recommended first server experiment. It compares Nvwa `RuleBased`
against the BFS-style `NodeBfs` baseline on the same Grok N256 sampled trace.

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 16 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK_SAMPLE_CSV" \
  --packetSize 64000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n256_k16_200perrank_pkt64k.csv \
  --log-dir results/grok_n256_k16_200perrank_pkt64k_logs \
  --max-retries 1
```

Check the result:

```bash
cat plots/grok_n256_k16_200perrank_pkt64k.csv
ls -lh results/grok_n256_k16_200perrank_pkt64k_logs
```

The CSV columns include `init_s`, `exec_s`, `wall_s`, `init_peak_mem_kb`,
`exec_peak_mem_gb`, `routing_entries`, `rule_based_rules`, and
`traffic_trace_flows`.

### 5. Increase Workload Pressure

After the 200-per-rank sample succeeds, increase the sample size. Keep the same
k=16 topology so all 1024 Grok ranks map one-to-one onto hosts.

```bash
GROK_SAMPLE_CSV=$GROK_DIR/grok_n256.1000perrank.nvwa.csv

python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i "$GROK_BIN" \
  -o "$GROK_SAMPLE_CSV" \
  --host-count 1024 \
  --max-flows-per-rank 1000 \
  --progress-interval 1000000

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 16 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK_SAMPLE_CSV" \
  --packetSize 64000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n256_k16_1000perrank_pkt64k.csv \
  --log-dir results/grok_n256_k16_1000perrank_pkt64k_logs \
  --max-retries 1
```

To make the packet-level execution phase heavier, reduce packet size:

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 16 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK_SAMPLE_CSV" \
  --packetSize 1000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n256_k16_1000perrank_pkt1k.csv \
  --log-dir results/grok_n256_k16_1000perrank_pkt1k_logs \
  --max-retries 1
```

`--packetSize 1000` creates many more ns-3 packet events than
`--packetSize 64000`, so expect much longer execution time.

### 6. Full Trace, Only If the Server Has Enough Resources

The full Grok N256 `.bin` is 34 GiB. The full converted CSV can be much larger,
and the current `constructor` path loads the CSV flows into memory before
installing replay traffic. Do not start the full run unless the server has ample
scratch space and RAM.

Full conversion:

```bash
GROK_FULL_CSV=$GROK_DIR/grok_n256.full.nvwa.csv

python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i "$GROK_BIN" \
  -o "$GROK_FULL_CSV" \
  --host-count 1024 \
  --progress-interval 1000000

ls -lh "$GROK_FULL_CSV"
```

Full k=16 RuleBased-only first:

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 16 \
  --routing RuleBased \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK_FULL_CSV" \
  --packetSize 64000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n256_k16_full_rulebased_pkt64k.csv \
  --log-dir results/grok_n256_k16_full_rulebased_pkt64k_logs \
  --max-retries 1
```

Only after the RuleBased full run succeeds, run the NodeBfs comparison:

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 16 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK_FULL_CSV" \
  --packetSize 64000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n256_k16_full_pkt64k.csv \
  --log-dir results/grok_n256_k16_full_pkt64k_logs \
  --max-retries 1
```

If full conversion or full replay is too large, stay with the sampled CSVs and
increase `--max-flows-per-rank` gradually. The sampled runs are still useful for
checking whether the real Grok communication pairs and message sizes preserve
the RuleBased-vs-NodeBfs initialization and memory trends.

## Server Runbook: Grok314B N512

Grok314B N512 is much larger than N256:

- Workload: `Grok314B_N512_GPU2048_TP4_PP1_CP1_VP1_EP8_ETP4_GBS4096`
- Ranks/GPUs: 2048
- Binary trace URL:
  `http://storage2.spcl.ethz.ch/traces/ai/grok/Grok314B_N512_GPU2048_TP4_PP1_CP1_VP1_EP8_ETP4_GBS4096/grok.bin`
- Binary size: about 135 GiB / 145,255,556,728 bytes

There is no exact k-ary FatTree with 2048 hosts because host count is `k^3 / 4`.
Use `k=24` for this experiment (`24^3 / 4 = 3456` hosts), matching the larger
paper-style FatTree size instead of the minimal-capacity `k=22`.

Prepare paths:

```bash
cd ~/Nvwa

GROK512_DIR=/data/wkli/grok314b_n512
mkdir -p "$GROK512_DIR" plots results

export GROK512_URL=http://storage2.spcl.ethz.ch/traces/ai/grok/Grok314B_N512_GPU2048_TP4_PP1_CP1_VP1_EP8_ETP4_GBS4096/grok.bin
export GROK512_BIN=$GROK512_DIR/grok_n512.bin
```

Download in the background:

```bash
export GROK512_URL GROK512_BIN
nohup bash -lc 'curl -L --fail -C - -o "$GROK512_BIN" "$GROK512_URL"' \
  > "$GROK512_DIR/download.log" 2>&1 &
echo $! > "$GROK512_DIR/download.pid"

tail -f "$GROK512_DIR/download.log"
```

Start with a smaller 50-per-rank sample:

```bash
export GROK512_SAMPLE_CSV=$GROK512_DIR/grok_n512.50perrank.nvwa.csv
export GROK512_BIN GROK512_SAMPLE_CSV

nohup bash -lc 'cd ~/Nvwa && python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i "$GROK512_BIN" \
  -o "$GROK512_SAMPLE_CSV" \
  --host-count 2048 \
  --max-flows-per-rank 50 \
  --progress-interval 1000000' \
  > "$GROK512_DIR/convert_50perrank.log" 2>&1 &
echo $! > "$GROK512_DIR/convert_50perrank.pid"

tail -f "$GROK512_DIR/convert_50perrank.log"
wc -l "$GROK512_SAMPLE_CSV"
head -n 5 "$GROK512_SAMPLE_CSV"
```

Run the k=24 comparison:

```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --only-k 24 \
  --routing RuleBased \
  --routing NodeBfs \
  --trafficPattern trace \
  --trafficReplayMode batch \
  --trafficTrace "$GROK512_SAMPLE_CSV" \
  --packetSize 64000 \
  --trafficTraceStopPadding 1 \
  --out plots/grok_n512_k24_50perrank_pkt64k.csv \
  --log-dir results/grok_n512_k24_50perrank_pkt64k_logs \
  --max-retries 1
```

After that succeeds, increase to 200 sends per rank:

```bash
export GROK512_SAMPLE_CSV=$GROK512_DIR/grok_n512.200perrank.nvwa.csv

nohup bash -lc 'cd ~/Nvwa && python3 src/datacenter/experiments/atlahs_bin_to_nvwa_trace.py \
  -i "$GROK512_BIN" \
  -o "$GROK512_SAMPLE_CSV" \
  --host-count 2048 \
  --max-flows-per-rank 200 \
  --progress-interval 1000000' \
  > "$GROK512_DIR/convert_200perrank.log" 2>&1 &
echo $! > "$GROK512_DIR/convert_200perrank.pid"
```

Then run the same sweep with output/log names changed to `200perrank`.
