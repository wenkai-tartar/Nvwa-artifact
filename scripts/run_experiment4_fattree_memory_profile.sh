#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  exec bash "${SCRIPT_DIR}/run_fattree_memory_profile.sh" "$@"
fi

source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment4_fattree_memory_profile" "${AE_ROOT}"
ae_start_run_log "experiment4_fattree_memory_profile"
ae_print_run_header

export AE_REUSE_RESULTS_DIR=1
exec bash "${SCRIPT_DIR}/run_fattree_memory_profile.sh" "$@"
