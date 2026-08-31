#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
NS3_ROOT="${NVWA_ROOT}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "fattree_ring_allreduce" "${AE_ROOT}"
ae_start_run_log "fattree_ring_allreduce"
ae_print_run_header
ae_install_signal_traps

GLOBAL_K_VALUES="${GLOBAL_K_VALUES:-8,16,24}"
NODEBFS_K_VALUES="${NODEBFS_K_VALUES:-8,16,24,32,40,48,56}"
RULEBASED_K_VALUES="${RULEBASED_K_VALUES:-8,16,24,32,40,48,56,64,72,80,88,96}"

REPEATS="${REPEATS:-1}"
DATA_SIZE="${DATA_SIZE:-1048576}"
DEGREE="${DEGREE:-4}"
if [[ "${THREADS:-1}" != "1" ]]; then
  echo "[info] Experiment 1 is single-threaded; ignoring THREADS=${THREADS} and using THREADS=1"
fi
THREADS=1
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-grouped-allreduce}"
ALLREDUCE_GROUP_SIZE="${ALLREDUCE_GROUP_SIZE:-8}"
ALLREDUCE_PLACEMENT="${ALLREDUCE_PLACEMENT:-strided}"
ALLREDUCE_STEP_GAP="${ALLREDUCE_STEP_GAP:-0}"
RUN_GLOBAL="${RUN_GLOBAL:-1}"
RUN_NODEBFS="${RUN_NODEBFS:-1}"
RUN_RULEBASED="${RUN_RULEBASED:-1}"
RESUME_POLICY="${RESUME_POLICY:-skip_success}"
SKIP_BUILD="${SKIP_BUILD:-0}"

export PYTHONPATH="${NS3_ROOT}:${NS3_ROOT}/src/datacenter/experiments:${NS3_ROOT}/src/datacenter/examples:${NS3_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -d "${NS3_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NS3_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

ROUTING_VALUES=()
if [[ "${RUN_GLOBAL}" == "1" ]]; then
  ROUTING_VALUES+=(--routing-values "Global:${GLOBAL_K_VALUES}")
fi
if [[ "${RUN_NODEBFS}" == "1" ]]; then
  ROUTING_VALUES+=(--routing-values "NodeBfs:${NODEBFS_K_VALUES}")
fi
if [[ "${RUN_RULEBASED}" == "1" ]]; then
  ROUTING_VALUES+=(--routing-values "RuleBased:${RULEBASED_K_VALUES}")
fi

if [[ "${#ROUTING_VALUES[@]}" -eq 0 ]]; then
  echo "[error] no routing selected" >&2
  exit 1
fi

EXTRA_ARGS=()
if [[ "${SKIP_BUILD}" == "1" ]]; then
  EXTRA_ARGS+=(--skip-build)
fi

cd "${AE_ROOT}"
ae_run python3 "${SCRIPT_DIR}/run_topology_ring_allreduce_stats.py" \
  --ns3-root "${NS3_ROOT}" \
  --topology fattree \
  "${ROUTING_VALUES[@]}" \
  --repeats "${REPEATS}" \
  --traffic-pattern "${TRAFFIC_PATTERN}" \
  --data-size "${DATA_SIZE}" \
  --degree "${DEGREE}" \
  --threads "${THREADS}" \
  --allreduce-group-size "${ALLREDUCE_GROUP_SIZE}" \
  --allreduce-placement "${ALLREDUCE_PLACEMENT}" \
  --allreduce-step-gap "${ALLREDUCE_STEP_GAP}" \
  --build-profile optimized \
  --resume-policy "${RESUME_POLICY}" \
  --out-dir "${RESULTS_DIR}" \
  --stats-name "experiment_1.csv" \
  --runs-name "experiment_1_runs.csv" \
  "${EXTRA_ARGS[@]}"

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_fattree_ring_allreduce.txt"

cat <<EOF
fattree_ring_allreduce_results=${RESULTS_DIR}
experiment_1_stats=${RESULTS_DIR}/experiment_1.csv
EOF
