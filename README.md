# Nüwa: A Generative Control Plane for AI Network Simulation

Nüwa, spelled `Nvwa` in repository paths, is a generative control plane for AI
network simulation. It targets large AI data-center simulations by generating
compact forwarding state for the simulated network, so the simulator can model
large topologies and AI communication workloads with lower initialization time
and memory overhead than conventional per-node routing-state construction.

This repository is the artifact for the paper "Nüwa: A Generative Control Plane
for AI Network Simulation." It contains the `Nvwa/` source tree, setup scripts,
experiment runners, plotting scripts, curated lightweight result data, and the
archived CSV inputs used to regenerate the final paper figures.

This artifact reproduces the paper's experimental figures:

- Figure 1(a)-(c): memory-stage, memory-composition, and NodeBfs initialization
  profiling.
- Figure 8(a)-(c): topology-scale execution memory for FatTree, Dragonfly, and
  Torus.
- Figure 9(a)-(c): topology-scale initialization time.
- Figure 10(a)-(d): topology-scale execution time and FatTree total time.
- Figure 11(a)-(d): workload-size execution time.
- Figure 12(a)-(b): ATLAHS Dragonfly production workload.
- Figure 13(a)-(b): FatTree failure handling.
- Figure 14(a)-(d): non-minimal routing overhead.

## Contents

- [Artifact Contents](#artifact-contents)
- [Reproduction Modes](#reproduction-modes)
- [CloudLab Server Setup](#cloudlab-server-setup)
- [From Scratch](#from-scratch)
- [Quick Checks](#quick-checks)
- [Running Experiments](#running-experiments)
- [Lightweight Experiments](#lightweight-experiments)
- [Full Experiments](#full-experiments)
- [Stopping Experiments](#stopping-experiments)
- [Plotting the Figures](#plotting-the-figures)
- [Appendix: Individual Lightweight Experiment Commands](#appendix-individual-lightweight-experiment-commands)
- [Appendix: Individual Full Experiment Commands](#appendix-individual-full-experiment-commands)

## Artifact Contents

The artifact has the following layout:

```bash
Nvwa-artifact/
  Nvwa/                         # Nüwa/ns-3 source tree
  scripts/                      # dependency, setup, and experiment scripts
  plots/                        # plotting scripts
  data/
    experiment_data/            # curated lightweight artifact CSV inputs
    archived_paper_data/        # archived final-paper CSV inputs
```

Use `data/experiment_data` for the reviewer-facing lightweight artifact results.
Use `data/archived_paper_data` when the goal is to reproduce the final paper
figures from the original paper CSV inputs without rerunning the longest
simulations.

## Reproduction Modes

The experiments in the original paper use large topologies and workloads. Some default
or paper-scale data points take hours or even days, which is impractical for the
artifact review process. To address this, the artifact uses a relatively lighter
workload. Although the numerical results may differ from the original paper, the
qualitative trends remain the same.

Even with the lighter workload, some large-scale data points can still take a long time to complete (e.g. fattree_k56_NodeBfs takes ~5 hours to complete). Therefore, for artifact review, we provide two reproduction modes:

- **Lightweight reproduction** runs small topology sizes, workload sizes, or
  trace lengths. These cases are intended to finish within 1 hour each on the recommended CloudLab machines. The numerical values can differ from the paper because the workload is smaller, but the expected trends are the
  same.
- **Full reproduction** runs the full-size experiment. These commands are
  much closer to the paper-scale workload, but they can take many hours or longer
  when run serially. Use this mode only when enough time and memory are
  available.

> [!IMPORTANT]
>  We do not recommend running multiple experiments simultaneously, as doing so may increase simulation time and the risk of out-of-memory (OOM) errors.

The original paper figures can be regenerated exactly from the archived CSV inputs:

```bash
bash plots/plot_figures.sh --full-data all
```

That path does not rerun the simulations; it reads `data/archived_paper_data`
and produces outputs under `results/full_data_figures/`.

## CloudLab Server Setup

Full large-scale experiments can require a server with more than 600 GB of memory.
If you already have access to a suitable machine, you can skip this section and
proceed directly to [From Scratch](#from-scratch).

For artifact review, we recommend using a high-memory bare-metal
node on CloudLab. Once the node is ready, SSH into it and follow the same setup
procedure described in [From Scratch](#from-scratch).

> [!NOTE]
> We do not provide a dedicated machine for artifact evaluation. Since the
> experiments are recommended to run exclusively on a single machine and can
> take a considerable amount of time to complete, sharing one server among
> multiple reviewers would likely lead to resource contention and scheduling
> difficulties. We therefore recommend that each reviewer provision a separate
> CloudLab node following the instructions below. We appreciate your
> understanding.

Recommended machine requirements:

- **Lightweight artifact review:** an Intel or AMD x86_64 Linux server with
  64GB RAM and 50GB free disk.
- **Full default reruns:** an Intel or AMD x86_64 Linux server with at least
  200GB free disk. Many full cases fit in 128-512GB RAM, but the largest
  paper-scale reruns may require about 600GB RAM.

All of the experiments in this artifact are single-threaded, so there is no
minimum CPU-core requirement for running one experiment data point. Newer or
faster cores reduce wall-clock time, and extra cores are only useful for the
build, OS overhead, or manually launching independent data points in parallel
(which is not recommended). The experiments are CPU-only and do not require a
GPU.

Recommended CloudLab node types:

- `r7525` on CloudLab Clemson: preferred CloudLab option for artifact review
  reruns; it provides 512GB RAM and local disk large enough for the artifact
  outputs.
- `d8545` on CloudLab Wisconsin: another suitable high-memory option with
  512GB RAM and NVMe storage, but only a small number of these nodes are
  available.

Lower-memory CloudLab nodes are not recommended as artifact-review defaults.
For example, 128GB and 192GB nodes can run the setup checks and explicitly
downsized experiments, but they are not suitable for the larger rerun subsets.

You can also check the current CloudLab node list for other options:
<https://docs.cloudlab.us/hardware.html>.


Suggested CloudLab flow:
```
1. Create an experiment with a single bare-metal node.
2. Select Ubuntu 24.04 as OS.
3. SSH to the allocated node and setup essential tools such as github.
```

## From Scratch

Once the machine is ready, follow the steps below to set up the artifact from scratch.

### 1. Clone the Repository

Clone the artifact repository and enter the repository root:

```bash
git clone git@github.com:wenkai-tartar/Nvwa-artifact.git
cd Nvwa-artifact
mkdir -p results
```

All commands below assume they are run from the repository root.

### 2. Install Dependencies

Install the Ubuntu packages required to build and run the artifact, including
`cmake`, compilers, ns-3 dependencies, Python, and Matplotlib:

```bash
bash scripts/install_ubuntu_deps.sh
```

Verify that CMake is available:

```bash
cmake --version
```

### 3. Build Optimized Binaries

Run the setup script:

```bash
bash scripts/setup_environment.sh
```

This builds the optimized standalone `Nvwa` ns-3 tree. After this step, run the
quick checks below, then use the lightweight or full reproduction commands for
the figures you want to regenerate. Setup logs are written under
`results/setup_<RUN_ID>/logs/`.

## Quick Checks

Use these two commands as the artifact-level sanity check. They are the intended
reviewer-facing replacement for per-experiment smoke tests.

```bash
bash scripts/check_environment.sh
bash scripts/kick_the_tires.sh
```

`check_environment.sh` verifies the checkout layout, required system tools,
Python plotting packages, shell-script syntax, Nvwa helper imports, and the
optimized constructor binary produced by `scripts/setup_environment.sh`.

`kick_the_tires.sh` runs two tiny representative experiment paths. It also renders Figure 1(c) from the fresh profiling output. The results are written under `results/kick_the_tires_<RUN_ID>/`.

The kick-the-tires result directory includes:

- `data/experiment_1.csv`
- `data/experiment_3_summary.csv`
- `data/experiment_3_time_profile.csv`
- `data/experiment_3_time_breakdown.csv`
- `figures/figure1c/figure1c.pdf`

## Running Experiments

Please run these experiments before plotting.

<table>
  <thead>
    <tr>
      <th width="60%">Experiment</th>
      <th width="40%">Figures</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><a href="#experiment-1-fattree-ring-allreduce-performance">Experiment 1: FatTree Ring AllReduce</a></td>
      <td>Figure 1(a), Figure 8(a), Figure 9(a), Figure 10(a), Figure 10(d)</td>
    </tr>
    <tr>
      <td><a href="#experiment-2-fattree-ring-allreduce-memory-profiling">Experiment 2: FatTree Memory Profile</a></td>
      <td>Figure 1(b)</td>
    </tr>
    <tr>
      <td><a href="#experiment-3-nodebfs-initialization-time-profiling">Experiment 3: NodeBfs Initialization Profile</a></td>
      <td>Figure 1(c)</td>
    </tr>
    <tr>
      <td><a href="#experiment-4-dragonfly-ring-allreduce-performance">Experiment 4: Dragonfly Ring AllReduce</a></td>
      <td>Figure 8(b), Figure 9(b), Figure 10(b)</td>
    </tr>
    <tr>
      <td><a href="#experiment-5-torus-ring-allreduce-performance">Experiment 5: Torus Ring AllReduce</a></td>
      <td>Figure 8(c), Figure 9(c), Figure 10(c)</td>
    </tr>
    <tr>
      <td><a href="#experiment-6-atlahs-production-workload-on-dragonfly">Experiment 6: ATLAHS Production Workload</a></td>
      <td>Figure 12(a)-(b)</td>
    </tr>
    <tr>
      <td><a href="#experiment-7-workload-size-ring-allreduce-performance">Experiment 7: Workload-Size AllReduce</a></td>
      <td>Figure 11(a)-(d)</td>
    </tr>
    <tr>
      <td><a href="#experiment-8-fattree-failure-handling">Experiment 8: FatTree Failure Handling</a></td>
      <td>Figure 13(a)-(b)</td>
    </tr>
    <tr>
      <td><a href="#experiment-9-non-minimal-routing-overhead">Experiment 9: Non-Minimal Routing</a></td>
      <td>Figure 14(a)-(d)</td>
    </tr>
  </tbody>
</table>

The lightweight and full one-command runners use the same flat data layout.
Their `data/` directory contains `experiment_1.csv`,
`experiment_2_summary.csv`, `experiment_2_memory_profile.csv`,
`experiment_2_object_profile.csv`, `experiment_3_summary.csv`,
`experiment_3_time_profile.csv`, `experiment_3_time_breakdown.csv`,
`experiment_4.csv`, `experiment_5.csv`, `experiment_6.csv`,
`experiment_6_manifest.json`, `experiment_7_dragonfly.csv`,
`experiment_7_fattree.csv`, `experiment_8.csv`, and `experiment_9.csv`.

### Lightweight Experiments

Run this command after completing [From Scratch](#from-scratch) and
[Quick Checks](#quick-checks). It runs the lightweight versions of Experiments
1-9 sequentially and plots the corresponding figures at the end:

```bash
bash scripts/run_lightweight_experiments.sh
```

The data files are written under
`results/lightweight_experiments_<RUN_ID>/data/`, and the generated figures are written under
`results/lightweight_experiments_<RUN_ID>/figures/`. Set `PLOT_AFTER=0` to run
only the experiments without plotting. Re-running the same command resumes the
latest lightweight suite and skips experiments that already completed
successfully; use `--rerun-all` to run all selected experiments again.

The lightweight commands use smaller workloads and are intended to finish in
under 1 hour per experiment on a recommended CloudLab node. To run only a
subset, pass experiment IDs:

```bash
bash scripts/run_lightweight_experiments.sh 1 4 5
```

To force a fresh run of the selected lightweight experiments:

```bash
bash scripts/run_lightweight_experiments.sh --rerun-all
```

For single-experiment reruns or debugging, see
[Appendix: Individual Lightweight Experiment Commands](#appendix-individual-lightweight-experiment-commands).

### Full Experiments

Run this command for the full experiments:

```bash
bash scripts/run_full_experiments.sh
```

This runs Experiments 1-9 sequentially and plots the corresponding figures at
the end. It writes data files under `results/full_experiments_<RUN_ID>/data/` and
figures under `results/full_experiments_<RUN_ID>/figures/`. Set `PLOT_AFTER=0`
to run only the experiments without plotting. Re-running the same command
resumes the latest full suite and skips experiments that already completed
successfully; use `--rerun-all` to run all selected experiments again.

The full run generates complete result sets,
but it can take many hours or longer when run serially. To run only a subset,
pass experiment IDs:

```bash
bash scripts/run_full_experiments.sh 1 4 5
```

To force a fresh run of the selected full experiments:

```bash
bash scripts/run_full_experiments.sh --rerun-all
```

For single-experiment full reruns or debugging, see
[Appendix: Individual Full Experiment Commands](#appendix-individual-full-experiment-commands).
For the exact final paper figure values, use
`bash plots/plot_figures.sh --full-data all` with the archived CSV inputs.

## Stopping Experiments

To stop currently running experiments launched from this artifact directory:

```bash
bash scripts/stop_experiments.sh
```

## Plotting the Figures

The one-command experiment scripts generate figures automatically. After
`bash scripts/run_lightweight_experiments.sh`, figures are in
`results/lightweight_experiments_<RUN_ID>/figures/`. After
`bash scripts/run_full_experiments.sh`, figures are in
`results/full_experiments_<RUN_ID>/figures/`.

If you set `PLOT_AFTER=0` or want to regenerate figures from fresh experiment
outputs, run:

```bash
bash plots/plot_figures.sh all
```

To regenerate only selected experiment figures, for example:

```bash
bash plots/plot_figures.sh 1 4 5
```

To plot directly from the included lightweight data files without rerunning
experiments:

```bash
bash plots/plot_figures.sh --lightweight-data all
```

This reads `data/experiment_data/` and writes figures under
`data/experiment_data/figures/`.

To plot directly from the included full paper data files without rerunning
experiments:

```bash
bash plots/plot_figures.sh --full-data all
```

This reads `data/archived_paper_data/` and writes figures under
`results/full_data_figures/`.

## Appendix: Individual Lightweight Experiment Commands

These commands are useful when rerunning or debugging a single experiment group.
After one individual experiment, generate the corresponding figure outputs with:

```bash
bash plots/plot_figures.sh <EXPERIMENT_ID>
```

For example, after Experiment 1:

```bash
bash plots/plot_figures.sh 1
```

### Experiment 1: FatTree Ring AllReduce Performance

```bash
GLOBAL_K_VALUES="8,16" \
NODEBFS_K_VALUES="8,16" \
RULEBASED_K_VALUES="8,16" \
REPEATS=1 SKIP_BUILD=1 \
  bash scripts/run_experiment1_fattree_ring_allreduce.sh
```

### Experiment 2: FatTree Ring AllReduce Memory Profiling

```bash
NODEBFS_K_VALUES="4,8,16" \
REPEATS=1 SKIP_BUILD=1 \
  bash scripts/run_experiment4_fattree_memory_profile.sh --routings NodeBfs
```

### Experiment 3: NodeBfs Initialization Time Profiling

```bash
K_VALUES="4,8,16" \
REPEATS=1 SKIP_BUILD=1 \
  bash scripts/run_experiment7_nodebfs_initialization_time_profile.sh
```

### Experiment 4: Dragonfly Ring AllReduce Performance

```bash
DRAGONFLY_H_VALUES="2,4" \
GLOBAL_H_VALUES="2,4" \
NODEBFS_H_VALUES="2,4" \
RULEBASED_H_VALUES="2,4" \
SKIP_BUILD=1 \
  bash scripts/run_experiment2_dragonfly_ring_allreduce.sh
```

### Experiment 5: Torus Ring AllReduce Performance

The lightweight Torus run keeps the expensive global-routing case at `d=5` and
uses `d=5,10` for the Nvwa and NodeBfs cases.

```bash
TORUS_D_VALUES="5,10" \
GLOBAL_D_VALUES="5" \
NODEBFS_D_VALUES="5,10" \
RULEBASED_D_VALUES="5,10" \
SKIP_BUILD=1 \
  bash scripts/run_experiment3_torus_ring_allreduce.sh
```

### Experiment 6: ATLAHS Production Workload on Dragonfly

This command truncates the external ATLAHS trace for a lightweight run. If the
trace has not already been cached, the first run may spend extra time
downloading it.

```bash
ATLAHS_CONVERT_MAX_FLOWS=5000 \
ATLAHS_MAX_FLOWS_PER_RANK=16 \
TRAFFIC_TRACE_MAX_FLOWS=5000 \
ROUTINGS="RuleBased,NodeBfs" \
SKIP_BUILD=1 \
  bash scripts/run_experiment6_atlahs_dragonfly_production_workload.sh
```

### Experiment 7: Workload-Size Ring AllReduce Performance

This lightweight run keeps the four Figure 11 panel topologies, but limits the
workload sweep to 1MB and 8MB and runs the Nvwa routing series.

```bash
DRAGONFLY_H_VALUES="4,6" \
FATTREE_K_VALUES="16,24" \
DATA_SIZE_VALUES="1048576,8388608" \
ROUTINGS="RuleBased" \
REPEATS=1 SKIP_BUILD=1 \
  bash scripts/run_experiment8_workload_size_allreduce.sh
```

### Experiment 8: FatTree Failure Handling

```bash
K_VALUES="8,16" \
BFS_K_VALUES="8,16" \
FAILURE_RATES="0.001" \
SKIP_BUILD=1 \
  bash scripts/run_experiment9_fattree_failure_handling.sh
```

### Experiment 9: Non-Minimal Routing Overhead

```bash
ONLY_GROUPS="dragonfly_valiant,torus_detour1" \
H_VALUES="2,4" \
D_VALUES="5" \
SKIP_BUILD=1 \
  bash scripts/run_experiment10_nonminimal_routing.sh
```

## Appendix: Individual Full Experiment Commands

These commands run the default artifact sweeps used by
`scripts/run_full_experiments.sh`. After one individual experiment, generate the
corresponding figure outputs with:

```bash
bash plots/plot_figures.sh <EXPERIMENT_ID>
```

| Experiment | Full command |
| --- | --- |
| 1 | `bash scripts/run_experiment1_fattree_ring_allreduce.sh` |
| 2 | `bash scripts/run_experiment4_fattree_memory_profile.sh` |
| 3 | `bash scripts/run_experiment7_nodebfs_initialization_time_profile.sh` |
| 4 | `bash scripts/run_experiment2_dragonfly_ring_allreduce.sh` |
| 5 | `bash scripts/run_experiment3_torus_ring_allreduce.sh` |
| 6 | `bash scripts/run_experiment6_atlahs_dragonfly_production_workload.sh` |
| 7 | `bash scripts/run_experiment8_workload_size_allreduce.sh` |
| 8 | `bash scripts/run_experiment9_fattree_failure_handling.sh` |
| 9 | `bash scripts/run_experiment10_nonminimal_routing.sh` |
