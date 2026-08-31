#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
source "${SCRIPT_DIR}/run_suite_helpers.sh"

usage() {
  cat <<'EOF'
Usage: bash scripts/run_full_experiments.sh [EXPERIMENT|all ...]

Runs the full/default versions of Experiments 1-9 sequentially. With no
arguments, all experiments are selected. By default, the runner resumes the
latest suite directory and skips experiments that already completed
successfully.

Options:
  --check       Run the environment check before experiments, default.
  --no-check    Skip the environment check.
  --plot        Plot figures after experiments, default.
  --no-plot     Skip figure generation.
  --rerun-all   Run selected experiments even if successful outputs exist.
  -h, --help    Show this help.

Environment:
  RESULTS_ROOT=/path/to/output   Parent directory for all experiment runs.
  SKIP_BUILD=0                   Rebuild inside experiment scripts.
  PLOT_AFTER=0                   Same as --no-plot.
  CHECK_ENV=0                    Same as --no-check.
  RERUN_ALL=1                    Same as --rerun-all.
  FORMATS=pdf,png                Figure formats when plotting.
EOF
}

RUN_ID_WAS_SET=0
if [[ -n "${RUN_ID:-}" ]]; then
  RUN_ID_WAS_SET=1
fi
RESULTS_ROOT_WAS_SET=0
if [[ -n "${RESULTS_ROOT:-}" ]]; then
  RESULTS_ROOT_WAS_SET=1
fi
CHECK_ENV="${CHECK_ENV:-1}"
PLOT_AFTER="${PLOT_AFTER:-1}"
RERUN_ALL="${RERUN_ALL:-0}"
FORMATS="${FORMATS:-pdf,png}"
FULL_SKIP_BUILD="${SKIP_BUILD:-1}"
RESUME_POLICY="${RESUME_POLICY:-skip_success}"

experiments=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ENV=1
      ;;
    --no-check)
      CHECK_ENV=0
      ;;
    --plot)
      PLOT_AFTER=1
      ;;
    --no-plot)
      PLOT_AFTER=0
      ;;
    --rerun-all)
      RERUN_ALL=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    all)
      experiments=(1 2 3 4 5 6 7 8 9)
      ;;
    *)
      if experiment="$(suite_normalize_experiment "$1")"; then
        experiments+=("${experiment}")
      else
        echo "[error] unknown argument or experiment ID: $1" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
  shift
done

if [[ "${#experiments[@]}" -eq 0 ]]; then
  experiments=(1 2 3 4 5 6 7 8 9)
fi

RUN_ID="${RUN_ID:-$(suite_timestamp)}"
LATEST_SUITE_POINTER="${AE_ROOT}/results/latest_full_experiments.txt"
REUSED_RESULTS_ROOT=0
if [[ "${RESULTS_ROOT_WAS_SET}" == "0" ]]; then
  if [[ "${RERUN_ALL}" != "1" && "${RUN_ID_WAS_SET}" == "0" ]] &&
    RESULTS_ROOT="$(suite_resolve_pointer "${LATEST_SUITE_POINTER}")"; then
    REUSED_RESULTS_ROOT=1
  else
    RESULTS_ROOT="${AE_ROOT}/results/full_experiments_${RUN_ID}"
  fi
fi
mkdir -p "${RESULTS_ROOT}"
RESULTS_ROOT="$(cd "${RESULTS_ROOT}" && pwd)"
RUN_LOG="${RESULTS_ROOT}/full_experiments_${RUN_ID}.log"

exec > >(tee -a "${RUN_LOG}") 2>&1

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_ROOT}" > "${AE_ROOT}/results/latest_full_experiments.txt"

echo "full_experiments_run_id=${RUN_ID}"
echo "full_experiments_results=${RESULTS_ROOT}"
echo "full_experiments_data=$(suite_data_dir "${RESULTS_ROOT}")"
echo "full_experiments_log=${RUN_LOG}"
echo "rerun_all=${RERUN_ALL}"
if [[ "${REUSED_RESULTS_ROOT}" == "1" ]]; then
  echo "resume_from_latest=1"
fi

run_step() {
  local experiment="$1"
  local name="$2"
  shift 2

  echo
  echo "==> Experiment ${experiment}: ${name}"
  local start_s end_s elapsed_s
  start_s="$(date +%s)"
  if (cd "${AE_ROOT}" && env AE_ROOT="${AE_ROOT}" RESULTS_ROOT="${RESULTS_ROOT}" RESUME_POLICY="${RESUME_POLICY}" SKIP_BUILD="${FULL_SKIP_BUILD}" "$@"); then
    local result_dir
    if ! result_dir="$(suite_mark_experiment_done "${RESULTS_ROOT}" "${experiment}")"; then
      echo "[error] Experiment ${experiment} finished but required output files are missing or failed" >&2
      echo "[error] Results root: ${RESULTS_ROOT}" >&2
      exit 1
    fi
    end_s="$(date +%s)"
    elapsed_s=$((end_s - start_s))
    echo "[done] Experiment ${experiment} finished in ${elapsed_s}s"
    echo "[done] result_dir=${result_dir}"
    echo "[done] data_dir=$(suite_data_dir "${RESULTS_ROOT}")"
  else
    local rc="$?"
    echo "[error] Experiment ${experiment} failed with exit code ${rc}" >&2
    echo "[error] Results root: ${RESULTS_ROOT}" >&2
    exit "${rc}"
  fi
}

run_experiment() {
  case "$1" in
    1)
      run_step 1 "FatTree Ring AllReduce" \
        bash "${SCRIPT_DIR}/run_experiment1_fattree_ring_allreduce.sh"
      ;;
    2)
      run_step 2 "FatTree Memory Profile" \
        bash "${SCRIPT_DIR}/run_experiment4_fattree_memory_profile.sh"
      ;;
    3)
      run_step 3 "NodeBfs Initialization Time Profile" \
        bash "${SCRIPT_DIR}/run_experiment7_nodebfs_initialization_time_profile.sh"
      ;;
    4)
      run_step 4 "Dragonfly Ring AllReduce" \
        bash "${SCRIPT_DIR}/run_experiment2_dragonfly_ring_allreduce.sh"
      ;;
    5)
      run_step 5 "Torus Ring AllReduce" \
        bash "${SCRIPT_DIR}/run_experiment3_torus_ring_allreduce.sh"
      ;;
    6)
      run_step 6 "ATLAHS Production Workload on Dragonfly" \
        bash "${SCRIPT_DIR}/run_experiment6_atlahs_dragonfly_production_workload.sh"
      ;;
    7)
      run_step 7 "Workload-Size Ring AllReduce" \
        bash "${SCRIPT_DIR}/run_experiment8_workload_size_allreduce.sh"
      ;;
    8)
      run_step 8 "FatTree Failure Handling" \
        bash "${SCRIPT_DIR}/run_experiment9_fattree_failure_handling.sh"
      ;;
    9)
      run_step 9 "Non-Minimal Routing Overhead" \
        bash "${SCRIPT_DIR}/run_experiment10_nonminimal_routing.sh"
      ;;
    *)
      echo "[error] internal error: unsupported experiment $1" >&2
      exit 2
      ;;
  esac
}

if [[ "${CHECK_ENV}" == "1" ]]; then
  echo
  echo "==> Checking environment"
  (cd "${AE_ROOT}" && AE_ROOT="${AE_ROOT}" bash "${SCRIPT_DIR}/check_environment.sh")
fi

ran_experiments=()
skipped_experiments=()
for experiment in "${experiments[@]}"; do
  if [[ "${RERUN_ALL}" != "1" ]] &&
    completed_dir="$(suite_completed_run_dir "${RESULTS_ROOT}" "${experiment}")"; then
    if ! data_dir="$(suite_publish_experiment_data "${RESULTS_ROOT}" "${experiment}" "${completed_dir}")"; then
      echo "[error] Experiment ${experiment} completed run exists, but published data files are missing" >&2
      echo "[error] result_dir=${completed_dir}" >&2
      exit 1
    fi
    echo
    echo "==> Experiment ${experiment}: already completed"
    echo "[skip] result_dir=${completed_dir}"
    echo "[skip] data_dir=${data_dir}"
    skipped_experiments+=("${experiment}")
    continue
  fi
  run_experiment "${experiment}"
  ran_experiments+=("${experiment}")
done

if [[ "${PLOT_AFTER}" == "1" ]]; then
  echo
  echo "==> Plotting figures"
  RESULTS_ROOT="${RESULTS_ROOT}" \
  OUT_ROOT="${RESULTS_ROOT}/figures" \
  FORMATS="${FORMATS}" \
    bash "${AE_ROOT}/plots/plot_figures.sh" "${experiments[@]}"
fi

echo
echo "full_experiments_status=passed"
echo "full_experiments_results=${RESULTS_ROOT}"
echo "full_experiments_data=$(suite_data_dir "${RESULTS_ROOT}")"
echo "full_experiments_ran=${ran_experiments[*]:-none}"
echo "full_experiments_skipped=${skipped_experiments[*]:-none}"
if [[ "${PLOT_AFTER}" == "1" ]]; then
  echo "full_experiments_figures=${RESULTS_ROOT}/figures"
fi
