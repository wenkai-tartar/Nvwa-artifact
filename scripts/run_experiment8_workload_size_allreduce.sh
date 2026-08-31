#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
NS3_ROOT="${NVWA_ROOT}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment8_workload_size_allreduce" "${AE_ROOT}"
ae_start_run_log "experiment8_workload_size_allreduce"
ae_print_run_header
ae_install_signal_traps

DATA_SIZE_VALUES_WAS_SET="${DATA_SIZE_VALUES+x}"
DRAGONFLY_H_VALUES="${DRAGONFLY_H_VALUES:-4,6}"
FATTREE_K_VALUES="${FATTREE_K_VALUES:-16,24}"
DATA_SIZE_VALUES="${DATA_SIZE_VALUES:-1048576,8388608,16777216,67108864,134217728}"
DRAGONFLY_H6_DATA_SIZE_VALUES="${DRAGONFLY_H6_DATA_SIZE_VALUES:-1048576,8388608,16777216}"
ROUTINGS="${ROUTINGS:-NodeBfs,RuleBased}"
REPEATS="${REPEATS:-1}"
DEGREE="${DEGREE:-4}"
if [[ "${THREADS:-1}" != "1" ]]; then
  echo "[info] Experiment 8 is single-threaded; ignoring THREADS=${THREADS} and using THREADS=1"
fi
THREADS=1
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-grouped-allreduce}"
ALLREDUCE_GROUP_SIZE="${ALLREDUCE_GROUP_SIZE:-8}"
ALLREDUCE_PLACEMENT="${ALLREDUCE_PLACEMENT:-strided}"
ALLREDUCE_STEP_GAP="${ALLREDUCE_STEP_GAP:-0}"
RUN_DRAGONFLY="${RUN_DRAGONFLY:-1}"
RUN_FATTREE="${RUN_FATTREE:-1}"
SKIP_BUILD="${SKIP_BUILD:-0}"
RESUME_POLICY="${RESUME_POLICY:-skip_success}"

export PYTHONPATH="${NS3_ROOT}:${NS3_ROOT}/src/datacenter/experiments:${NS3_ROOT}/src/datacenter/examples:${NS3_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -d "${NS3_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NS3_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

if [[ "${RUN_DRAGONFLY}" != "1" && "${RUN_FATTREE}" != "1" ]]; then
  echo "[error] no topology selected" >&2
  exit 1
fi

cd "${AE_ROOT}"

run_sweep() {
  local topology="$1"
  local values="$2"
  local out_dir="$3"
  local data_size_values="${4:-${DATA_SIZE_VALUES}}"
  local stats_name="$5"
  local runs_name="$6"
  local build_args=()

  if [[ "${SKIP_BUILD}" == "1" ]]; then
    build_args+=(--skip-build)
  fi

  ae_run python3 "${SCRIPT_DIR}/run_topology_ring_allreduce_stats.py" \
    --ns3-root "${NS3_ROOT}" \
    --topology "${topology}" \
    --values "${values}" \
    --routings "${ROUTINGS}" \
    --repeats "${REPEATS}" \
    --traffic-pattern "${TRAFFIC_PATTERN}" \
    --data-size-values "${data_size_values}" \
    --degree "${DEGREE}" \
    --threads "${THREADS}" \
    --allreduce-group-size "${ALLREDUCE_GROUP_SIZE}" \
    --allreduce-placement "${ALLREDUCE_PLACEMENT}" \
    --allreduce-step-gap "${ALLREDUCE_STEP_GAP}" \
    --build-profile optimized \
    --resume-policy "${RESUME_POLICY}" \
    --out-dir "${out_dir}" \
    --stats-name "${stats_name}" \
    --runs-name "${runs_name}" \
    "${build_args[@]}"

}

if [[ "${RUN_DRAGONFLY}" == "1" ]]; then
  IFS=',' read -r -a dragonfly_values <<< "${DRAGONFLY_H_VALUES}"
  for h_value in "${dragonfly_values[@]}"; do
    h_value="${h_value//[[:space:]]/}"
    if [[ -z "${h_value}" ]]; then
      continue
    fi
    h_data_size_values="${DATA_SIZE_VALUES}"
    if [[ -z "${DATA_SIZE_VALUES_WAS_SET}" && "${h_value}" == "6" ]]; then
      h_data_size_values="${DRAGONFLY_H6_DATA_SIZE_VALUES}"
    fi
    run_sweep "dragonfly" "${h_value}" "${RESULTS_DIR}/dragonfly" "${h_data_size_values}" \
      "experiment_7_dragonfly.csv" "experiment_7_dragonfly_runs.csv"
  done
fi

if [[ "${RUN_FATTREE}" == "1" ]]; then
  run_sweep "fattree" "${FATTREE_K_VALUES}" "${RESULTS_DIR}/fattree" "${DATA_SIZE_VALUES}" \
    "experiment_7_fattree.csv" "experiment_7_fattree_runs.csv"
fi

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_workload_size_allreduce.txt"

echo "experiment8_results=${RESULTS_DIR}"
if [[ "${RUN_DRAGONFLY}" == "1" ]]; then
  echo "experiment_7_dragonfly_stats=${RESULTS_DIR}/dragonfly/experiment_7_dragonfly.csv"
fi
if [[ "${RUN_FATTREE}" == "1" ]]; then
  echo "experiment_7_fattree_stats=${RESULTS_DIR}/fattree/experiment_7_fattree.csv"
fi
