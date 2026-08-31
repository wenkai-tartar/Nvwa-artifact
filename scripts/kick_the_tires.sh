#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
source "${SCRIPT_DIR}/run_suite_helpers.sh"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RESULTS_ROOT="${RESULTS_ROOT:-${AE_ROOT}/results/kick_the_tires_${RUN_ID}}"
export AE_ROOT RESULTS_ROOT

mkdir -p "${RESULTS_ROOT}"
RESULTS_ROOT="$(cd "${RESULTS_ROOT}" && pwd)"
export RESULTS_ROOT

echo "kick_the_tires_results=${RESULTS_ROOT}"

echo
echo "==> Checking environment"
bash "${SCRIPT_DIR}/check_environment.sh" --require-build

echo
echo "==> Running a tiny FatTree Ring AllReduce experiment"
GLOBAL_K_VALUES="${KICK_FATTREE_GLOBAL_K_VALUES:-4}" \
NODEBFS_K_VALUES="${KICK_FATTREE_NODEBFS_K_VALUES:-4}" \
RULEBASED_K_VALUES="${KICK_FATTREE_RULEBASED_K_VALUES:-4}" \
REPEATS="${KICK_REPEATS:-1}" \
SKIP_BUILD=1 \
  bash "${SCRIPT_DIR}/run_experiment1_fattree_ring_allreduce.sh"

fat_tree_dir="$(<"${RESULTS_ROOT}/current_experiment1_fattree_ring_allreduce.txt")"
if [[ ! -s "${fat_tree_dir}/experiment_1.csv" ]]; then
  echo "[error] FatTree quick run did not produce experiment_1.csv" >&2
  exit 1
fi
data_dir="$(suite_publish_experiment_data "${RESULTS_ROOT}" 1 "${fat_tree_dir}")"

echo
echo "==> Running a tiny NodeBfs initialization-time profiling experiment"
K_VALUES="${KICK_NODEBFS_K_VALUES:-4}" \
ROUTINGS="${KICK_NODEBFS_ROUTINGS:-NodeBfs}" \
REPEATS="${KICK_REPEATS:-1}" \
SKIP_BUILD=1 \
  bash "${SCRIPT_DIR}/run_experiment7_nodebfs_initialization_time_profile.sh"

nodebfs_dir="$(<"${RESULTS_ROOT}/current_experiment7_nodebfs_initialization_time_profile.txt")"
if [[ ! -s "${nodebfs_dir}/experiment_3_time_breakdown.csv" ]]; then
  echo "[error] NodeBfs quick run did not produce experiment_3_time_breakdown.csv" >&2
  exit 1
fi
data_dir="$(suite_publish_experiment_data "${RESULTS_ROOT}" 3 "${nodebfs_dir}")"

echo
echo "==> Rendering one quick figure from the fresh profiling run"
FORMATS="${KICK_FORMATS:-pdf}" \
RUN_DIR="${data_dir}" \
OUT_ROOT="${RESULTS_ROOT}/figures" \
RESULTS_ROOT="${RESULTS_ROOT}" \
  bash "${AE_ROOT}/plots/plot_figures.sh" 3

cat <<EOF
kick_the_tires_status=passed
kick_the_tires_results=${RESULTS_ROOT}
kick_the_tires_data=${data_dir}
fattree_quick_results=${fat_tree_dir}
nodebfs_quick_results=${nodebfs_dir}
quick_figure=${RESULTS_ROOT}/figures/figure1c/figure1c.pdf
EOF
