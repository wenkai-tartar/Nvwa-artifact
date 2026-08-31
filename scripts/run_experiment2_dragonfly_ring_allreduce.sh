#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
NS3_ROOT="${NVWA_ROOT}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment2_dragonfly_ring_allreduce" "${AE_ROOT}"
ae_start_run_log "experiment2_dragonfly_ring_allreduce"
ae_print_run_header
ae_install_signal_traps

DRAGONFLY_H_VALUES_WAS_SET="${DRAGONFLY_H_VALUES+x}"
DRAGONFLY_H_VALUES="${DRAGONFLY_H_VALUES:-2,4,6,8,10,14}"
GLOBAL_H_VALUES="${GLOBAL_H_VALUES:-}"
if [[ -z "${GLOBAL_H_VALUES}" ]]; then
  if [[ -n "${DRAGONFLY_H_VALUES_WAS_SET}" ]]; then
    GLOBAL_H_VALUES="${DRAGONFLY_H_VALUES}"
  else
    GLOBAL_H_VALUES="2,4,6"
  fi
fi
NODEBFS_H_VALUES="${NODEBFS_H_VALUES:-${DRAGONFLY_H_VALUES}}"
RULEBASED_H_VALUES="${RULEBASED_H_VALUES:-${DRAGONFLY_H_VALUES}}"
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-grouped-allreduce}"
DATA_SIZE="${DATA_SIZE:-1048576}"
if [[ "${THREADS:-1}" != "1" ]]; then
  echo "[info] Experiment 2 is single-threaded; ignoring THREADS=${THREADS} and using THREADS=1"
fi
THREADS=1
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
  ROUTING_VALUES+=(--routing-values "Global:${GLOBAL_H_VALUES}")
fi
if [[ "${RUN_NODEBFS}" == "1" ]]; then
  ROUTING_VALUES+=(--routing-values "NodeBfs:${NODEBFS_H_VALUES}")
fi
if [[ "${RUN_RULEBASED}" == "1" ]]; then
  ROUTING_VALUES+=(--routing-values "RuleBased:${RULEBASED_H_VALUES}")
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
  --topology dragonfly \
  "${ROUTING_VALUES[@]}" \
  --traffic-pattern "${TRAFFIC_PATTERN}" \
  --data-size "${DATA_SIZE}" \
  --threads "${THREADS}" \
  --allreduce-group-size "${ALLREDUCE_GROUP_SIZE}" \
  --allreduce-placement "${ALLREDUCE_PLACEMENT}" \
  --allreduce-step-gap "${ALLREDUCE_STEP_GAP}" \
  --build-profile optimized \
  --resume-policy "${RESUME_POLICY}" \
  --out-dir "${RESULTS_DIR}" \
  --stats-name "experiment_4.csv" \
  --runs-name "experiment_4_runs.csv" \
  "${EXTRA_ARGS[@]}"

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_dragonfly_ring_allreduce.txt"

cat <<EOF
experiment2_results=${RESULTS_DIR}
experiment_4_stats=${RESULTS_DIR}/experiment_4.csv
EOF
