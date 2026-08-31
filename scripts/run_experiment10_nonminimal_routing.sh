#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment10_nonminimal_routing" "${AE_ROOT}"
ae_start_run_log "experiment10_nonminimal_routing"
ae_print_run_header
ae_install_signal_traps

ONLY_GROUPS="${ONLY_GROUPS:-dragonfly_valiant,dragonfly_ugal,torus_detour1,torus_detour2}"
H_VALUES="${H_VALUES:-2,4,6,8,10}"
D_VALUES="${D_VALUES:-5,10,15,20}"
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-grouped-allreduce}"
NUM_FLOWS="${NUM_FLOWS:-10}"
FLOW_SIZE="${FLOW_SIZE:-1048576}"
DATA_SIZE="${DATA_SIZE:-1048576}"
ALLREDUCE_GROUP_SIZE="${ALLREDUCE_GROUP_SIZE:-8}"
ALLREDUCE_PLACEMENT="${ALLREDUCE_PLACEMENT:-strided}"
ALLREDUCE_STEP_GAP="${ALLREDUCE_STEP_GAP:-0}"
BANDWIDTH="${BANDWIDTH:-100Gbps}"
DELAY="${DELAY:-1us}"
BUILD_PROFILE="${BUILD_PROFILE:-optimized}"
SKIP_BUILD="${SKIP_BUILD:-0}"
RESUME_POLICY="${RESUME_POLICY:-skip_success}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_SLEEP="${RETRY_SLEEP:-0.2}"

if [[ ! -d "${NVWA_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NVWA_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

export PYTHONPATH="${NVWA_ROOT}:${NVWA_ROOT}/src/datacenter/experiments:${NVWA_ROOT}/src/datacenter/examples:${NVWA_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

extra_args=()
if [[ "${SKIP_BUILD}" == "1" ]]; then
  extra_args+=(--skip-build)
fi

cd "${NVWA_ROOT}"
ae_run python3 src/datacenter/experiments/nonminimal_sweep.py \
  --build-profile "${BUILD_PROFILE}" \
  --bandwidth "${BANDWIDTH}" \
  --delay "${DELAY}" \
  --trafficPattern "${TRAFFIC_PATTERN}" \
  --numFlows "${NUM_FLOWS}" \
  --flowSize "${FLOW_SIZE}" \
  --dataSize "${DATA_SIZE}" \
  --allreduceGroupSize "${ALLREDUCE_GROUP_SIZE}" \
  --allreducePlacement "${ALLREDUCE_PLACEMENT}" \
  --allreduceStepGap "${ALLREDUCE_STEP_GAP}" \
  --only "${ONLY_GROUPS}" \
  --only-h "${H_VALUES}" \
  --only-d "${D_VALUES}" \
  --out "${RESULTS_DIR}/experiment_9.csv" \
  --log-dir "${RESULTS_DIR}/logs" \
  --resume-policy "${RESUME_POLICY}" \
  --max-retries "${MAX_RETRIES}" \
  --retry-sleep "${RETRY_SLEEP}" \
  "${extra_args[@]}"

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_nonminimal_routing.txt"

cat <<EOF
experiment10_results=${RESULTS_DIR}
experiment_9_nonminimal_stats=${RESULTS_DIR}/experiment_9.csv
experiment10_nonminimal_logs=${RESULTS_DIR}/logs
EOF
