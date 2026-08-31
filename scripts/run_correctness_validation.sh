#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "correctness_validation" "${AE_ROOT}"
ae_start_run_log "correctness_validation"
ae_print_run_header

CORRECTNESS_K="${CORRECTNESS_K:-4}"
BANDWIDTH="${BANDWIDTH:-100Gbps}"
DELAY="${DELAY:-1us}"

export PYTHONPATH="${NVWA_ROOT}:${NVWA_ROOT}/src/datacenter/examples:${NVWA_ROOT}/src/datacenter/examples/inputs:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -d "${NVWA_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NVWA_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

cd "${NVWA_ROOT}"

generator_log="${RESULTS_DIR}/generate_topology.log"
generator_output="$(
  python3 src/datacenter/examples/inputs/topology_generator.py \
    fattree \
    --k "${CORRECTNESS_K}" \
    --bandwidth "${BANDWIDTH}" \
    --delay "${DELAY}" \
    --routing RuleBased 2>&1 | tee "${generator_log}"
)"

CONFIG="$(
  printf '%s\n' "${generator_output}" |
    awk -F': ' '/^Output file:/ {print $2}' |
    tail -n 1
)"

if [[ -z "${CONFIG}" ]]; then
  echo "[error] could not parse generated FatTree config from ${generator_log}" >&2
  exit 1
fi

compare_log="${RESULTS_DIR}/compare_rulebased_nodebfs.log"
python3 src/datacenter/examples/compare_constructor_packet_traces.py \
  --config "${CONFIG}" \
  --algos RuleBased NodeBfs \
  --ns3 ./ns3 2>&1 | tee "${compare_log}"

config_stem="${CONFIG%.json}"
trace_dir="${NVWA_ROOT}/src/datacenter/examples/traces"
cp "${trace_dir}/${config_stem}_RuleBased_packet_trace.txt" "${RESULTS_DIR}/"
cp "${trace_dir}/${config_stem}_NodeBfs_packet_trace.txt" "${RESULTS_DIR}/"

mkdir -p "${AE_ROOT}/results"
printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_correctness_validation.txt"

cat <<EOF
correctness_results=${RESULTS_DIR}
correctness_config=${CONFIG}
correctness_log=${compare_log}
EOF
