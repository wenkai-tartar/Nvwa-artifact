#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment1_fattree_ring_allreduce" "${AE_ROOT}"
ae_start_run_log "experiment1_fattree_ring_allreduce"
ae_print_run_header

export AE_REUSE_RESULTS_DIR=1
exec bash "${SCRIPT_DIR}/run_fattree_ring_allreduce.sh" "$@"
