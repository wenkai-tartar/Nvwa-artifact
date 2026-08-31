#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment9_fattree_failure_handling" "${AE_ROOT}"
ae_start_run_log "experiment9_fattree_failure_handling"
ae_print_run_header
ae_install_signal_traps

K_VALUES="${K_VALUES:-8,16,24,32,40,48,56,64}"
if [[ -z "${BFS_K_VALUES+x}" ]]; then
  if [[ "${K_VALUES}" == "8,16,24,32,40,48,56,64" ]]; then
    BFS_K_VALUES="8,16,24,32,40,48,56"
  else
    BFS_K_VALUES="${K_VALUES}"
  fi
fi
FAILURE_RATES="${FAILURE_RATES:-0.001}"
ROUTING="${ROUTING:-RuleBased}"
BFS_ROUTING="${BFS_ROUTING:-NodeBfs}"
RUN_BFS="${RUN_BFS:-1}"
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-allreduce}"
NUM_FLOWS="${NUM_FLOWS:-10}"
FLOW_SIZE="${FLOW_SIZE:-1048576}"
RANDOM_FAILURE_TIME="${RANDOM_FAILURE_TIME:-0.5}"
RANDOM_FAILURE_TIME_UNIT="${RANDOM_FAILURE_TIME_UNIT:-s}"
RANDOM_FAILURE_SEED="${RANDOM_FAILURE_SEED:-1}"
BANDWIDTH="${BANDWIDTH:-100Gbps}"
DELAY="${DELAY:-1us}"
BUILD_PROFILE="${BUILD_PROFILE:-optimized}"
SKIP_BUILD="${SKIP_BUILD:-0}"
RESUME_POLICY="${RESUME_POLICY:-skip_success}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_SLEEP="${RETRY_SLEEP:-0.2}"
RECORD_FAILURES="${RECORD_FAILURES:-0}"

if [[ ! -d "${NVWA_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NVWA_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

export PYTHONPATH="${NVWA_ROOT}:${NVWA_ROOT}/src/datacenter/experiments:${NVWA_ROOT}/src/datacenter/examples:${NVWA_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

common_args=()
if [[ "${SKIP_BUILD}" == "1" ]]; then
  common_args+=(--skip-build)
fi
if [[ "${RECORD_FAILURES}" == "1" ]]; then
  common_args+=(--record-failures)
fi

cd "${NVWA_ROOT}"
ae_run python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --build-profile "${BUILD_PROFILE}" \
  --routing "${ROUTING}" \
  --bfs-routing "${BFS_ROUTING}" \
  --bandwidth "${BANDWIDTH}" \
  --delay "${DELAY}" \
  --trafficPattern "${TRAFFIC_PATTERN}" \
  --numFlows "${NUM_FLOWS}" \
  --flowSize "${FLOW_SIZE}" \
  --randomFailureTime "${RANDOM_FAILURE_TIME}" \
  --randomFailureTimeUnit "${RANDOM_FAILURE_TIME_UNIT}" \
  --randomFailureSeed "${RANDOM_FAILURE_SEED}" \
  --only-k "${K_VALUES}" \
  --only-fr "${FAILURE_RATES}" \
  --out "${RESULTS_DIR}/experiment_8.csv" \
  --log-dir "${RESULTS_DIR}/logs" \
  --failure-json-dir "${RESULTS_DIR}/failure-json" \
  --resume-policy "${RESUME_POLICY}" \
  --max-retries "${MAX_RETRIES}" \
  --retry-sleep "${RETRY_SLEEP}" \
  --no-bfs \
  "${common_args[@]}"

if [[ "${RUN_BFS}" == "1" && -n "${BFS_K_VALUES}" ]]; then
  bfs_args=("${common_args[@]}")
  if [[ "${SKIP_BUILD}" != "1" ]]; then
    bfs_args+=(--skip-build)
  fi

  ae_run python3 src/datacenter/experiments/fattree_failure_sweep.py \
    --build-profile "${BUILD_PROFILE}" \
    --routing "${ROUTING}" \
    --bfs-routing "${BFS_ROUTING}" \
    --bandwidth "${BANDWIDTH}" \
    --delay "${DELAY}" \
    --trafficPattern "${TRAFFIC_PATTERN}" \
    --numFlows "${NUM_FLOWS}" \
    --flowSize "${FLOW_SIZE}" \
    --randomFailureTime "${RANDOM_FAILURE_TIME}" \
    --randomFailureTimeUnit "${RANDOM_FAILURE_TIME_UNIT}" \
    --randomFailureSeed "${RANDOM_FAILURE_SEED}" \
    --only-k "${BFS_K_VALUES}" \
    --only-fr "${FAILURE_RATES}" \
    --out "${RESULTS_DIR}/experiment_8.csv" \
    --log-dir "${RESULTS_DIR}/logs" \
    --failure-json-dir "${RESULTS_DIR}/failure-json" \
    --resume-policy "${RESUME_POLICY}" \
    --max-retries "${MAX_RETRIES}" \
    --retry-sleep "${RETRY_SLEEP}" \
    "${bfs_args[@]}"
fi

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_fattree_failure_handling.txt"

cat <<EOF
experiment9_results=${RESULTS_DIR}
experiment_8_failure_stats=${RESULTS_DIR}/experiment_8.csv
experiment9_failure_logs=${RESULTS_DIR}/logs
experiment9_failure_json=${RESULTS_DIR}/failure-json
EOF
