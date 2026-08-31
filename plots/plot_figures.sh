#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PLOTTERS_DIR="${SCRIPT_DIR}/plotters"
ARCHIVED_PAPER_DIR="${PLOTTERS_DIR}/archived_paper"

MODE="${MODE:-experiment}"
DATA_ROOT="${DATA_ROOT:-}"
RESULTS_ROOT="${RESULTS_ROOT:-}"
RESULTS_ROOT_WAS_SET=0
if [[ -n "${RESULTS_ROOT}" ]]; then
  RESULTS_ROOT_WAS_SET=1
fi
RUN_DIR="${RUN_DIR:-}"
OUT_ROOT="${OUT_ROOT:-}"
OUT_DIR="${OUT_DIR:-}"
FORMATS="${FORMATS:-pdf,png}"
INCLUDE_PERF="${INCLUDE_PERF:-0}"
INCLUDE_FAILED="${INCLUDE_FAILED:-0}"
FAILURE_RATE="${FAILURE_RATE:-}"

PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"
export PYTHONDONTWRITEBYTECODE
if [[ -z "${PYTHONNOUSERSITE+x}" ]]; then
  export PYTHONNOUSERSITE=1
fi

usage() {
  cat <<'EOF'
Usage:
  bash plots/plot_figures.sh EXPERIMENT|all ...
  bash plots/plot_figures.sh --lightweight-data [EXPERIMENT|all ...]
  bash plots/plot_figures.sh --full-data [all]

Examples:
  bash plots/plot_figures.sh all
  bash plots/plot_figures.sh --lightweight-data all
  bash plots/plot_figures.sh --lightweight-data 1 4 5
  bash plots/plot_figures.sh --full-data all
  bash plots/plot_figures.sh 1
  RUN_DIR=/path/to/results/experiment10_nonminimal_routing_<RUN_ID> bash plots/plot_figures.sh 9

Options:
  --lightweight-data     Plot from included lightweight data in data/experiment_data.
  --full-data            Plot from included full paper data in data/archived_paper_data.
  --data-root DIR        Plot from a lightweight-data style directory.
  --results-root DIR     Directory containing latest/current result pointers.
  --run-dir DIR          Plot one experiment from an explicit result directory.
  --out-root DIR         Write generated figure directories under DIR.
  --formats LIST         Comma-separated output formats, default pdf,png.
  --include-perf         Include full-data performance comparison helper output.
  --include-failed       Include failed rows when supported by a plotter.
  --failure-rate VALUE   Select a failure rate for Figure 13.
  -h, --help             Show this help.

Experiment IDs:
  1  FatTree ring allreduce                 -> figure1a figure8a figure9a figure10a figure10d
  2  FatTree memory profiling               -> figure1b
  3  NodeBfs initialization time profiling  -> figure1c
  4  Dragonfly ring allreduce               -> figure8b figure9b figure10b
  5  Torus ring allreduce                   -> figure8c figure9c figure10c
  6  ATLAHS Dragonfly workload              -> figure12
  7  Workload-size allreduce                -> figure11a figure11b figure11c figure11d
  8  FatTree failure handling               -> figure13a figure13b
  9  Non-minimal routing                    -> figure14a figure14b figure14c figure14d
EOF
}

die() {
  echo "[error] $*" >&2
  exit 1
}

require_value() {
  local opt="$1"
  local value="${2:-}"
  if [[ -z "${value}" ]]; then
    die "${opt} requires a value"
  fi
}

positionals=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --lightweight-data)
      MODE="lightweight_data"
      shift
      ;;
    --full-data)
      MODE="full_data"
      shift
      ;;
    --data-root)
      require_value "$1" "${2:-}"
      DATA_ROOT="$2"
      MODE="lightweight_data"
      shift 2
      ;;
    --results-root)
      require_value "$1" "${2:-}"
      RESULTS_ROOT="$2"
      RESULTS_ROOT_WAS_SET=1
      shift 2
      ;;
    --run-dir)
      require_value "$1" "${2:-}"
      RUN_DIR="$2"
      shift 2
      ;;
    --out-root)
      require_value "$1" "${2:-}"
      OUT_ROOT="$2"
      shift 2
      ;;
    --out-dir)
      require_value "$1" "${2:-}"
      OUT_DIR="$2"
      shift 2
      ;;
    --formats)
      require_value "$1" "${2:-}"
      FORMATS="$2"
      shift 2
      ;;
    --include-perf)
      INCLUDE_PERF=1
      shift
      ;;
    --include-failed)
      INCLUDE_FAILED=1
      shift
      ;;
    --failure-rate)
      require_value "$1" "${2:-}"
      FAILURE_RATE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "[error] unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

if [[ "${MODE}" != "full_data" && -n "${DATA_ROOT}" ]]; then
  MODE="lightweight_data"
fi

normalize_path_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    die "directory not found: ${path}"
  fi
  cd "${path}" && pwd
}

normalize_experiment() {
  local value="${1,,}"
  value="${value#experiment}"
  value="${value#exp}"
  case "${value}" in
    1|2|3|4|5|6|7|8|9) printf '%s\n' "${value}" ;;
    *) return 1 ;;
  esac
}

figures_for_experiment() {
  case "$1" in
    1) printf '%s\n' figure1a figure8a figure9a figure10a figure10d ;;
    2) printf '%s\n' figure1b ;;
    3) printf '%s\n' figure1c ;;
    4) printf '%s\n' figure8b figure9b figure10b ;;
    5) printf '%s\n' figure8c figure9c figure10c ;;
    6) printf '%s\n' figure12 ;;
    7) printf '%s\n' figure11a figure11b figure11c figure11d ;;
    8) printf '%s\n' figure13a figure13b ;;
    9) printf '%s\n' figure14a figure14b figure14c figure14d ;;
    *) return 1 ;;
  esac
}

candidate_result_pointers() {
  case "$1" in
    1) printf '%s\n' latest_fattree_ring_allreduce.txt current_experiment1_fattree_ring_allreduce.txt ;;
    2) printf '%s\n' latest_fattree_memory_profile.txt current_experiment4_fattree_memory_profile.txt ;;
    3) printf '%s\n' latest_nodebfs_initialization_time_profile.txt current_experiment7_nodebfs_initialization_time_profile.txt ;;
    4) printf '%s\n' latest_dragonfly_ring_allreduce.txt current_experiment2_dragonfly_ring_allreduce.txt ;;
    5) printf '%s\n' latest_torus_ring_allreduce.txt current_experiment3_torus_ring_allreduce.txt ;;
    6) printf '%s\n' latest_atlahs_dragonfly_production_workload.txt current_experiment6_atlahs_dragonfly_production_workload.txt ;;
    7) printf '%s\n' latest_workload_size_allreduce.txt current_experiment8_workload_size_allreduce.txt ;;
    8) printf '%s\n' latest_fattree_failure_handling.txt current_experiment9_fattree_failure_handling.txt ;;
    9) printf '%s\n' latest_nonminimal_routing.txt current_experiment10_nonminimal_routing.txt ;;
    *) return 1 ;;
  esac
}

candidate_result_globs() {
  case "$1" in
    1) printf '%s\n' experiment1_fattree_ring_allreduce_* ;;
    2) printf '%s\n' experiment4_fattree_memory_profile_* ;;
    3) printf '%s\n' experiment7_nodebfs_initialization_time_profile_* ;;
    4) printf '%s\n' experiment2_dragonfly_ring_allreduce_* ;;
    5) printf '%s\n' experiment3_torus_ring_allreduce_* ;;
    6) printf '%s\n' experiment6_atlahs_dragonfly_production_workload_* ;;
    7) printf '%s\n' experiment8_workload_size_allreduce_* ;;
    8) printf '%s\n' experiment9_fattree_failure_handling_* ;;
    9) printf '%s\n' experiment10_nonminimal_routing_* ;;
    *) return 1 ;;
  esac
}

resolve_pointer() {
  local pointer="$1"
  [[ -f "${pointer}" ]] || return 1

  local target
  target="$(<"${pointer}")"
  [[ -n "${target}" ]] || return 1

  if [[ "${target}" != /* ]]; then
    target="$(cd "$(dirname "${pointer}")" && pwd)/${target}"
  fi
  if [[ -f "${target}" ]]; then
    target="$(dirname "${target}")"
  fi
  [[ -d "${target}" ]] || return 1
  cd "${target}" && pwd
}

latest_result_dir() {
  local pattern="$1"
  find "${RESULTS_ROOT}" -maxdepth 1 -type d -name "${pattern}" -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | sed -n '1s/^[^ ]* //p'
}

flat_data_complete() {
  local experiment="$1"
  local data_dir="$2"
  [[ -d "${data_dir}" ]] || return 1

  case "${experiment}" in
    1) [[ -s "${data_dir}/experiment_1.csv" ]] ;;
    2)
      [[ -s "${data_dir}/experiment_2_summary.csv" ]] &&
        [[ -s "${data_dir}/experiment_2_memory_profile.csv" ]] &&
        [[ -s "${data_dir}/experiment_2_object_profile.csv" ]]
      ;;
    3)
      [[ -s "${data_dir}/experiment_3_summary.csv" ]] &&
        [[ -s "${data_dir}/experiment_3_time_profile.csv" ]] &&
        [[ -s "${data_dir}/experiment_3_time_breakdown.csv" ]]
      ;;
    4) [[ -s "${data_dir}/experiment_4.csv" ]] ;;
    5) [[ -s "${data_dir}/experiment_5.csv" ]] ;;
    6) [[ -s "${data_dir}/experiment_6.csv" ]] ;;
    7)
      [[ -s "${data_dir}/experiment_7_dragonfly.csv" ]] &&
        [[ -s "${data_dir}/experiment_7_fattree.csv" ]]
      ;;
    8) [[ -s "${data_dir}/experiment_8.csv" ]] ;;
    9) [[ -s "${data_dir}/experiment_9.csv" ]] ;;
    *) return 1 ;;
  esac
}

resolve_run_dir() {
  local experiment="$1"

  if [[ -z "${DATA_ROOT}" && -n "${RUN_DIR}" ]]; then
    normalize_path_dir "${RUN_DIR}"
    return 0
  fi

  if [[ -n "${DATA_ROOT}" ]]; then
    if flat_data_complete "${experiment}" "${DATA_ROOT}"; then
      cd "${DATA_ROOT}" && pwd
      return 0
    fi
    die "missing lightweight data file(s) for experiment ${experiment} under ${DATA_ROOT}"
  fi

  if flat_data_complete "${experiment}" "${RESULTS_ROOT}/data"; then
    cd "${RESULTS_ROOT}/data" && pwd
    return 0
  fi

  if flat_data_complete "${experiment}" "${RESULTS_ROOT}"; then
    cd "${RESULTS_ROOT}" && pwd
    return 0
  fi

  local pointer
  while IFS= read -r pointer; do
    [[ -n "${pointer}" ]] || continue
    if resolve_pointer "${RESULTS_ROOT}/${pointer}"; then
      return 0
    fi
  done < <(candidate_result_pointers "${experiment}")

  local pattern
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] || continue
    local latest
    latest="$(latest_result_dir "${pattern}")"
    if [[ -n "${latest}" ]]; then
      cd "${latest}" && pwd
      return 0
    fi
  done < <(candidate_result_globs "${experiment}")

  die "no result directory found for experiment ${experiment} under ${RESULTS_ROOT}; run the experiment first, set RUN_DIR, or use --lightweight-data"
}

out_dir_for_figure() {
  local run_dir="$1"
  local figure="$2"

  if [[ -n "${OUT_ROOT}" ]]; then
    printf '%s/%s\n' "${OUT_ROOT%/}" "${figure}"
  elif [[ -n "${DATA_ROOT}" ]]; then
    printf '%s/figures/%s\n' "${DATA_ROOT}" "${figure}"
  else
    printf '%s/figures/%s\n' "${run_dir}" "${figure}"
  fi
}

run_python() {
  echo "+ ${*}"
  "$@"
}

run_figure() {
  local experiment="$1"
  local figure="$2"
  local run_dir="$3"
  local out_dir="$4"
  local script="${PLOTTERS_DIR}/plot_${figure}.py"

  [[ -f "${script}" ]] || die "plotter not found: ${script}"

  case "${figure}" in
    figure1a)
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        --run-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --routing "${ROUTING:-NodeBfs}" \
        --formats "${FORMATS}"
      ;;
    figure1b)
      run_python python3 "${script}" \
        --experiment-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --routings "${FIGURE1B_ROUTINGS:-${ROUTING:-NodeBfs}}" \
        --figure figure1b \
        --figure1b-mode "${FIGURE1B_MODE:-auto}" \
        --formats "${FORMATS}"
      ;;
    figure1c)
      run_python python3 "${script}" \
        --run-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}"
      ;;
    figure8*|figure9*|figure10*)
      local -a topology_args=()
      case "${experiment}" in
        1) topology_args+=(--fattree-dir "${run_dir}") ;;
        4) topology_args+=(--dragonfly-dir "${run_dir}") ;;
        5) topology_args+=(--torus-dir "${run_dir}") ;;
        *) die "${figure} is not associated with experiment ${experiment}" ;;
      esac
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        "${topology_args[@]}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}"
      ;;
    figure11*)
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        --run-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}"
      ;;
    figure12)
      local -a extra_args=()
      if [[ "${INCLUDE_FAILED}" == "1" ]]; then
        extra_args+=(--include-failed)
      fi
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        --experiment-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}" \
        "${extra_args[@]}"
      ;;
    figure13*)
      local -a extra_args=()
      if [[ "${INCLUDE_FAILED}" == "1" ]]; then
        extra_args+=(--include-failed)
      fi
      if [[ -n "${FAILURE_RATE}" ]]; then
        extra_args+=(--failure-rate "${FAILURE_RATE}")
      fi
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        --run-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}" \
        "${extra_args[@]}"
      ;;
    figure14*)
      local -a extra_args=()
      if [[ "${INCLUDE_FAILED}" == "1" ]]; then
        extra_args+=(--include-failed)
      fi
      run_python python3 "${script}" \
        --results-root "${RESULTS_ROOT}" \
        --run-dir "${run_dir}" \
        --out-dir "${out_dir}" \
        --formats "${FORMATS}" \
        "${extra_args[@]}"
      ;;
    *)
      die "unsupported figure: ${figure}"
      ;;
  esac
}

publish_pdf() {
  local out_base="$1"
  local map_file="$2"
  local figure="$3"
  local source_name="$4"
  local source_path="${out_base}/${source_name}"
  local figure_dir="${out_base}/${figure}"
  local normalized_path="${figure_dir}/${figure}.pdf"

  if [[ ! -f "${source_path}" ]]; then
    echo "[warn] missing full-data output: ${source_path}" >&2
    return
  fi

  mkdir -p "${figure_dir}"
  cp "${source_path}" "${normalized_path}"
  printf '%s,%s,%s\n' "${figure}" "${source_name}" "${figure}/${figure}.pdf" >> "${map_file}"
}

plot_full_data() {
  if [[ "${#positionals[@]}" -gt 0 ]]; then
    local arg
    for arg in "${positionals[@]}"; do
      if [[ "${arg,,}" != "all" ]]; then
        die "--full-data plots all full-data figures; experiment IDs are not supported"
      fi
    done
  fi

  local archived_data_dir="${ARCHIVED_DATA_DIR:-${AE_ROOT}/data/archived_paper_data}"
  archived_data_dir="$(normalize_path_dir "${archived_data_dir}")"

  local out_base
  out_base="${OUT_ROOT:-${OUT_DIR:-${AE_ROOT}/results/full_data_figures}}"
  mkdir -p "${out_base}"
  out_base="$(cd "${out_base}" && pwd)"

  echo "[full-data] Figure 1(a)"
  run_python python3 "${PLOTTERS_DIR}/plot_figure1a.py" \
    --stats-csv "${archived_data_dir}/final_figure1/figure1a/fattree_ring_allreduce_stats.csv" \
    --out-dir "${out_base}/figure1a" \
    --formats "${FORMATS}"

  echo "[full-data] Figure 1(b)"
  run_python python3 "${PLOTTERS_DIR}/plot_figure1b.py" \
    --experiment-dir "${archived_data_dir}/final_figure1/figure1b" \
    --out-dir "${out_base}/figure1b" \
    --routings NodeBfs \
    --figure figure1b \
    --figure1b-mode auto \
    --memory-profile-name memory_profile.csv \
    --formats "${FORMATS}"

  echo "[full-data] Figure 1(c)"
  run_python python3 "${PLOTTERS_DIR}/plot_figure1c.py" \
    --run-dir "${archived_data_dir}/final_figure1/figure1c" \
    --out-dir "${out_base}/figure1c" \
    --time-breakdown-name time_breakdown.csv \
    --formats "${FORMATS}"

  local paper_scripts=(
    "plot_mem_legend.py"
    "plot_mem-ar.py"
    "plot_init_exe-ar.py"
    "plot_total-ar.py"
    "plot_mem-data.py"
    "plot_failure.py"
    "plot_nonminimal_exe-mem.py"
  )

  if [[ "${INCLUDE_PERF}" == "1" ]]; then
    paper_scripts+=("plot_perf.py")
  fi

  local script
  for script in "${paper_scripts[@]}"; do
    echo "[full-data] ${script}"
    echo "+ ARCHIVED_DATA_DIR=${archived_data_dir} OUT_DIR=${out_base} python3 ${ARCHIVED_PAPER_DIR}/${script}"
    ARCHIVED_DATA_DIR="${archived_data_dir}" OUT_DIR="${out_base}" \
      python3 "${ARCHIVED_PAPER_DIR}/${script}"
  done

  local map_file="${out_base}/full_data_figure_outputs.csv"
  printf 'figure,source,normalized_output\n' > "${map_file}"
  printf '%s,%s,%s\n' \
    figure1a final_figure1/figure1a/fattree_ring_allreduce_stats.csv figure1a/figure1a.pdf \
    figure1b final_figure1/figure1b/ns3_datacenter_nodebfs/memory_profile.csv figure1b/figure1b.pdf \
    figure1c final_figure1/figure1c/time_breakdown.csv figure1c/figure1c.pdf \
    >> "${map_file}"

  publish_pdf "${out_base}" "${map_file}" figure8a mem_fattree-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure8b mem_dragonfly-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure8c mem_torus-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure9a init_fattree-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure9b init_dragonfly-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure9c init_torus-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure10a exec_fattree-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure10b exec_dragonfly-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure10c exec_torus-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure10d total_fattree-ar.pdf
  publish_pdf "${out_base}" "${map_file}" figure11a exec_dragonfly_h4.pdf
  publish_pdf "${out_base}" "${map_file}" figure11b exec_dragonfly_h6.pdf
  publish_pdf "${out_base}" "${map_file}" figure11c exec_fattree_k16.pdf
  publish_pdf "${out_base}" "${map_file}" figure11d exec_fattree_k24.pdf
  publish_pdf "${out_base}" "${map_file}" figure13a failure-fattree-exec.pdf
  publish_pdf "${out_base}" "${map_file}" figure13b failure-fattree-mem.pdf
  publish_pdf "${out_base}" "${map_file}" figure14a nonminimal-dragonfly-exec.pdf
  publish_pdf "${out_base}" "${map_file}" figure14b nonminimal-dragonfly-mem.pdf
  publish_pdf "${out_base}" "${map_file}" figure14c nonminimal-torus-exec.pdf
  publish_pdf "${out_base}" "${map_file}" figure14d nonminimal-torus-mem.pdf

  echo "[full-data] Figure 12"
  run_python python3 "${PLOTTERS_DIR}/plot_figure12.py" \
    --experiment-dir "${archived_data_dir}/final_figure12" \
    --out-dir "${out_base}/figure12" \
    --summary-name summary.csv \
    --formats "${FORMATS}"

  printf '%s,%s,%s\n' \
    figure12a final_figure12/summary.csv figure12/figure12a.pdf \
    figure12b final_figure12/summary.csv figure12/figure12b.pdf \
    >> "${map_file}"

  echo "full_data_figures=${out_base}"
}

plot_experiments() {
  if [[ "${MODE}" == "lightweight_data" ]]; then
    DATA_ROOT="${DATA_ROOT:-${AE_ROOT}/data/experiment_data}"
  fi

  if [[ -n "${DATA_ROOT}" ]]; then
    DATA_ROOT="$(normalize_path_dir "${DATA_ROOT}")"
  fi

  if [[ -z "${RESULTS_ROOT}" ]]; then
    if [[ -n "${DATA_ROOT}" ]]; then
      RESULTS_ROOT="${DATA_ROOT}"
    else
      RESULTS_ROOT="${AE_ROOT}/results"
    fi
  elif [[ "${RESULTS_ROOT_WAS_SET}" == "0" && -n "${DATA_ROOT}" ]]; then
    RESULTS_ROOT="${DATA_ROOT}"
  fi
  mkdir -p "${RESULTS_ROOT}"
  RESULTS_ROOT="$(cd "${RESULTS_ROOT}" && pwd)"

  if [[ -n "${OUT_ROOT}" ]]; then
    mkdir -p "${OUT_ROOT}"
    OUT_ROOT="$(cd "${OUT_ROOT}" && pwd)"
  fi

  local experiments=()
  local arg experiment
  if [[ "${#positionals[@]}" -eq 0 && "${MODE}" == "lightweight_data" ]]; then
    positionals=(all)
  fi
  if [[ "${#positionals[@]}" -gt 0 ]]; then
    for arg in "${positionals[@]}"; do
      if [[ "${arg,,}" == "all" ]]; then
        experiments=(1 2 3 4 5 6 7 8 9)
        break
      fi
      if ! experiment="$(normalize_experiment "${arg}")"; then
        echo "[error] unknown experiment: ${arg}" >&2
        usage >&2
        exit 2
      fi
      experiments+=("${experiment}")
    done
  elif [[ -n "${EXPERIMENTS:-}" ]]; then
    read -r -a requested <<<"${EXPERIMENTS//,/ }"
    for arg in "${requested[@]}"; do
      [[ -n "${arg}" ]] || continue
      if [[ "${arg,,}" == "all" ]]; then
        experiments=(1 2 3 4 5 6 7 8 9)
        break
      fi
      if ! experiment="$(normalize_experiment "${arg}")"; then
        echo "[error] unknown experiment: ${arg}" >&2
        usage >&2
        exit 2
      fi
      experiments+=("${experiment}")
    done
  elif [[ -n "${EXPERIMENT:-}" ]]; then
    if ! experiment="$(normalize_experiment "${EXPERIMENT}")"; then
      echo "[error] unknown experiment: ${EXPERIMENT}" >&2
      usage >&2
      exit 2
    fi
    experiments+=("${experiment}")
  else
    usage >&2
    exit 2
  fi

  if [[ -z "${DATA_ROOT}" && -n "${RUN_DIR}" && "${#experiments[@]}" -ne 1 ]]; then
    die "RUN_DIR can only be used when plotting one experiment"
  fi

  local run_dir figure
  for experiment in "${experiments[@]}"; do
    run_dir="$(resolve_run_dir "${experiment}")"
    echo "experiment${experiment}_source=${run_dir}"

    while IFS= read -r figure; do
      [[ -n "${figure}" ]] || continue
      echo "[experiment ${experiment}] ${figure}"
      run_figure "${experiment}" "${figure}" "${run_dir}" "$(out_dir_for_figure "${run_dir}" "${figure}")"
    done < <(figures_for_experiment "${experiment}")
  done
}

case "${MODE}" in
  full_data)
    plot_full_data
    ;;
  lightweight_data|experiment)
    plot_experiments
    ;;
  *)
    die "unknown MODE=${MODE}"
    ;;
esac
