#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
NS3_ROOT="${NVWA_ROOT}"
source "${SCRIPT_DIR}/run_helpers.sh"

usage() {
  cat <<'EOF'
Usage: run_fattree_memory_profile.sh [--routings LIST|all]

LIST is a comma-separated list using Global, NodeBfs, and/or RuleBased.
Examples:
  bash scripts/run_fattree_memory_profile.sh --routings NodeBfs
  bash scripts/run_fattree_memory_profile.sh --routings Global,RuleBased
  bash scripts/run_fattree_memory_profile.sh --routings all

Legacy RUN_GLOBAL/RUN_NODEBFS/RUN_RULEBASED environment switches are still
supported and override the routing list one by one when set.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --routing|--routings)
      if [[ $# -lt 2 ]]; then
        echo "[error] $1 requires a value" >&2
        exit 1
      fi
      ROUTINGS="$2"
      shift 2
      ;;
    --all)
      ROUTINGS="all"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[error] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

GLOBAL_K_VALUES="${GLOBAL_K_VALUES:-4,8,16}"
NODEBFS_K_VALUES="${NODEBFS_K_VALUES:-4,8,16}"
RULEBASED_K_VALUES="${RULEBASED_K_VALUES:-4,8,16}"

REPEATS="${REPEATS:-1}"
DATA_SIZE="${DATA_SIZE:-1048576}"
DEGREE="${DEGREE:-4}"
TRAFFIC_PATTERN="${TRAFFIC_PATTERN:-allreduce}"
ROUTINGS="${ROUTINGS:-NodeBfs}"
SKIP_BUILD="${SKIP_BUILD:-0}"
DERIVED_RUN_GLOBAL=0
DERIVED_RUN_NODEBFS=0
DERIVED_RUN_RULEBASED=0

enable_routing() {
  local token
  token="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d ' _-')"
  case "${token}" in
    all)
      DERIVED_RUN_GLOBAL=1
      DERIVED_RUN_NODEBFS=1
      DERIVED_RUN_RULEBASED=1
      ;;
    global|ns3global)
      DERIVED_RUN_GLOBAL=1
      ;;
    nodebfs|ns3datacenternodebfs|datacenternodebfs)
      DERIVED_RUN_NODEBFS=1
      ;;
    rulebased|nvwarulebased)
      DERIVED_RUN_RULEBASED=1
      ;;
    "")
      ;;
    *)
      echo "[error] unknown routing in ROUTINGS: $1" >&2
      exit 1
      ;;
  esac
}

IFS=',' read -r -a ROUTING_TOKENS <<< "${ROUTINGS}"
for routing_token in "${ROUTING_TOKENS[@]}"; do
  enable_routing "${routing_token}"
done

RUN_GLOBAL="${RUN_GLOBAL:-${DERIVED_RUN_GLOBAL}}"
RUN_NODEBFS="${RUN_NODEBFS:-${DERIVED_RUN_NODEBFS}}"
RUN_RULEBASED="${RUN_RULEBASED:-${DERIVED_RUN_RULEBASED}}"

if [[ "${RUN_GLOBAL}" != "1" && "${RUN_NODEBFS}" != "1" && "${RUN_RULEBASED}" != "1" ]]; then
  echo "[error] no routing sweep selected; set ROUTINGS=Global,NodeBfs,RuleBased or one RUN_* flag" >&2
  exit 1
fi

ae_init_results_dir "fattree_memory_profile" "${AE_ROOT}"
ae_start_run_log "fattree_memory_profile"
ae_print_run_header
ae_install_signal_traps

FIRST_ENABLED_SWEEP=1

export PYTHONPATH="${NS3_ROOT}:${NS3_ROOT}/src/datacenter/experiments:${NS3_ROOT}/src/datacenter/examples:${NS3_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -d "${NS3_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NS3_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

run_sweep() {
  local label="$1"
  local routing="$2"
  local k_values="$3"
  local skip_build="$4"
  local out_dir="${RESULTS_DIR}/${label}"
  local extra_args=()

  if [[ "${FIRST_ENABLED_SWEEP}" == "1" ]]; then
    if [[ "${SKIP_BUILD}" == "1" ]]; then
      skip_build="yes"
    else
      skip_build="no"
    fi
    FIRST_ENABLED_SWEEP=0
  elif [[ "${SKIP_BUILD}" == "1" ]]; then
    skip_build="yes"
  fi

  if [[ "${skip_build}" == "yes" ]]; then
    extra_args+=(--skip-build)
  fi

  cd "${NS3_ROOT}"
  ae_run python3 src/datacenter/experiments/fattree_memory_profile_sweep.py \
    --k-values "${k_values}" \
    --routings "${routing}" \
    --repeats "${REPEATS}" \
    --data-size "${DATA_SIZE}" \
    --degree "${DEGREE}" \
    --traffic-pattern "${TRAFFIC_PATTERN}" \
    --build-profile optimized \
    --out-dir "${out_dir}" \
    --summary-name "experiment_2_summary.csv" \
    --memory-profile-name "experiment_2_memory_profile.csv" \
    --object-profile-name "experiment_2_object_profile.csv" \
    "${extra_args[@]}"
}

if [[ "${RUN_GLOBAL}" == "1" ]]; then
  run_sweep "ns3_global" "Global" "${GLOBAL_K_VALUES}" "no"
fi
if [[ "${RUN_NODEBFS}" == "1" ]]; then
  run_sweep "ns3_datacenter_nodebfs" "NodeBfs" "${NODEBFS_K_VALUES}" "yes"
fi
if [[ "${RUN_RULEBASED}" == "1" ]]; then
  run_sweep "nvwa_rulebased" "RuleBased" "${RULEBASED_K_VALUES}" "yes"
fi

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_fattree_memory_profile.txt"

cat <<EOF
fattree_memory_profile_results=${RESULTS_DIR}
experiment_2_summary=${RESULTS_DIR}/<routing>/experiment_2_summary.csv
experiment_2_memory_profile=${RESULTS_DIR}/<routing>/experiment_2_memory_profile.csv
experiment_2_object_profile=${RESULTS_DIR}/<routing>/experiment_2_object_profile.csv
EOF
