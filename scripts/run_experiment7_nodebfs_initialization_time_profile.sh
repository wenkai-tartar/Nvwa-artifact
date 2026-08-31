#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment7_nodebfs_initialization_time_profile" "${AE_ROOT}"
ae_start_run_log "experiment7_nodebfs_initialization_time_profile"
ae_print_run_header
ae_install_signal_traps

K_VALUES="${K_VALUES:-4,8,16}"
ROUTINGS="${ROUTINGS:-NodeBfs}"
REPEATS="${REPEATS:-1}"
DATA_SIZE="${DATA_SIZE:-1048576}"
DATA_RATE="${DATA_RATE:-100Gbps}"
DEGREE="${DEGREE:-4}"
PACKET_SIZE="${PACKET_SIZE:-1000}"
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-allreduce}"
TRAFFIC_REPLAY_MODE="${TRAFFIC_REPLAY_MODE:-batch}"
BANDWIDTH="${BANDWIDTH:-100Gbps}"
DELAY="${DELAY:-1us}"
SKIP_BUILD="${SKIP_BUILD:-0}"

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
ae_run python3 src/datacenter/experiments/fattree_time_profile_sweep.py \
  --k-values "${K_VALUES}" \
  --routings "${ROUTINGS}" \
  --repeats "${REPEATS}" \
  --data-size "${DATA_SIZE}" \
  --data-rate "${DATA_RATE}" \
  --degree "${DEGREE}" \
  --packet-size "${PACKET_SIZE}" \
  --traffic-pattern "${TRAFFIC_PATTERN}" \
  --traffic-replay-mode "${TRAFFIC_REPLAY_MODE}" \
  --bandwidth "${BANDWIDTH}" \
  --delay "${DELAY}" \
  --build-profile optimized \
  --out-dir "${RESULTS_DIR}" \
  --summary-name "experiment_3_summary.csv" \
  --time-profile-name "experiment_3_time_profile.csv" \
  --time-breakdown-name "experiment_3_time_breakdown.csv" \
  "${extra_args[@]}"

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_nodebfs_initialization_time_profile.txt"

cat <<EOF
experiment7_results=${RESULTS_DIR}
experiment_3_summary=${RESULTS_DIR}/experiment_3_summary.csv
experiment_3_time_profile=${RESULTS_DIR}/experiment_3_time_profile.csv
experiment_3_time_breakdown=${RESULTS_DIR}/experiment_3_time_breakdown.csv
EOF
