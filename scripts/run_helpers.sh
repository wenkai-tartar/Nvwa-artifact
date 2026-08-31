#!/usr/bin/env bash

ae_utc_timestamp() {
  date -u +%Y%m%dT%H%M%S%NZ
}

ae_init_results_dir() {
  local prefix="$1"
  local script_dir="$2"
  local results_root="${RESULTS_ROOT:-${script_dir}/results}"

  if [[ "${AE_REUSE_RESULTS_DIR:-0}" == "1" && -n "${RESULTS_DIR:-}" ]]; then
    RUN_ID="${RUN_ID:-$(ae_utc_timestamp)}"
  else
    RUN_ID="$(ae_utc_timestamp)"
    RESULTS_DIR="${results_root}/${prefix}_${RUN_ID}"
  fi

  mkdir -p "${RESULTS_DIR}"
  printf '%s\n' "${RESULTS_DIR}" > "${results_root}/current_${prefix}.txt"
  export RUN_ID
  export RESULTS_DIR
  export AE_RESULTS_ROOT="${results_root}"
}

ae_start_run_log() {
  local prefix="$1"

  if [[ "${AE_LOG_ACTIVE:-0}" == "1" && -n "${RUN_LOG:-}" ]]; then
    return 0
  fi

  RUN_LOG="${RESULTS_DIR}/${prefix}_${RUN_ID}.log"
  printf '%s\n' "${RUN_LOG}" > "${AE_RESULTS_ROOT}/current_${prefix}_log.txt"
  export RUN_LOG
  export AE_LOG_ACTIVE=1
  exec > >(tee -a "${RUN_LOG}") 2>&1
}

ae_print_run_header() {
  if [[ "${AE_RUN_HEADER_PRINTED:-0}" == "1" ]]; then
    return 0
  fi

  export AE_RUN_HEADER_PRINTED=1
  echo "run_id=${RUN_ID}"
  echo "results_dir=${RESULTS_DIR}"
  if [[ -n "${RUN_LOG:-}" ]]; then
    echo "run_log=${RUN_LOG}"
  fi
}

ae_child_pgid=""

ae_terminate_child_group() {
  local signal_name="${1:-TERM}"
  if [[ -n "${ae_child_pgid}" ]]; then
    kill "-${signal_name}" -- "-${ae_child_pgid}" 2>/dev/null || true
  fi
}

ae_signal_handler() {
  ae_terminate_child_group TERM
  sleep "${AE_STOP_GRACE_SECONDS:-5}"
  ae_terminate_child_group KILL
  exit 143
}

ae_install_signal_traps() {
  trap ae_signal_handler TERM INT
}

ae_run() {
  setsid "$@" &
  ae_child_pgid="$!"
  wait "${ae_child_pgid}"
  local rc="$?"
  ae_child_pgid=""
  return "${rc}"
}
