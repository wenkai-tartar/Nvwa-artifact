#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
source "${SCRIPT_DIR}/run_helpers.sh"

ae_init_results_dir "experiment6_atlahs_dragonfly_production_workload" "${AE_ROOT}"
ae_start_run_log "experiment6_atlahs_dragonfly_production_workload"
ae_print_run_header
ae_install_signal_traps

export NVWA_ROOT

DEFAULT_ATLAHS_TRACE_URL="http://storage2.spcl.ethz.ch/traces/ai/llama/Llama7B_N4_GPU16_TP1_PP1_DP16_BS32/llama.bin"
DEFAULT_ATLAHS_TRACE_NAME="llama/Llama7B_N4_GPU16_TP1_PP1_DP16_BS32/llama.bin"
ATLAHS_TRACE_URL="${ATLAHS_TRACE_URL:-${DEFAULT_ATLAHS_TRACE_URL}}"
ATLAHS_TRACE_CACHE_DIR="${ATLAHS_TRACE_CACHE_DIR:-${AE_RESULTS_ROOT}/atlahs_traces}"
ATLAHS_TRACE_CACHE_FILE="${ATLAHS_TRACE_CACHE_FILE:-}"

if [[ ! -d "${NVWA_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NVWA_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before running experiments" >&2
  exit 1
fi

if [[ -z "${ATLAHS_TRACE:-}" ]]; then
  if [[ -z "${ATLAHS_TRACE_URL}" ]]; then
    cat >&2 <<'EOF'
[error] ATLAHS_TRACE is required when ATLAHS_TRACE_URL is empty.

Set ATLAHS_TRACE to one of:
  - an ATLAHS/LogGOPSim .bin schedule;
  - an ATLAHS .goal schedule;
  - an already converted Nvwa CSV with columns start_s,src,dst,bytes[,tag].

Example:
  ATLAHS_TRACE=/data/atlahs/grok_n256.bin \
    bash scripts/run_experiment6_atlahs_dragonfly_production_workload.sh
EOF
    exit 2
  fi

  if [[ -n "${ATLAHS_TRACE_CACHE_FILE}" ]]; then
    ATLAHS_TRACE="${ATLAHS_TRACE_CACHE_FILE}"
  elif [[ "${ATLAHS_TRACE_URL}" == "${DEFAULT_ATLAHS_TRACE_URL}" ]]; then
    ATLAHS_TRACE="${ATLAHS_TRACE_CACHE_DIR}/${DEFAULT_ATLAHS_TRACE_NAME}"
  else
    trace_url_path="${ATLAHS_TRACE_URL%%\?*}"
    ATLAHS_TRACE="${ATLAHS_TRACE_CACHE_DIR}/custom/$(basename "${trace_url_path}")"
  fi
  mkdir -p "$(dirname "${ATLAHS_TRACE}")"
  if [[ ! -f "${ATLAHS_TRACE}" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "[error] curl not found; install curl or set ATLAHS_TRACE to a local trace file" >&2
      exit 1
    fi
    echo "[download] ${ATLAHS_TRACE_URL}"
    echo "[download] -> ${ATLAHS_TRACE}"
    ae_run curl -L --fail -C - -o "${ATLAHS_TRACE}" "${ATLAHS_TRACE_URL}"
  else
    echo "[download] reusing cached ATLAHS trace: ${ATLAHS_TRACE}"
  fi
fi

if [[ ! -f "${ATLAHS_TRACE}" ]]; then
  echo "[error] ATLAHS_TRACE does not exist or is not a file: ${ATLAHS_TRACE}" >&2
  exit 1
fi

TRACE_INPUT="$(readlink -f "${ATLAHS_TRACE}")"
NVWA_EXPERIMENTS_DIR="${NVWA_ROOT}/src/datacenter/experiments"
BIN_CONVERTER="${NVWA_EXPERIMENTS_DIR}/atlahs_bin_to_nvwa_trace.py"
GOAL_CONVERTER="${NVWA_EXPERIMENTS_DIR}/atlahs_goal_to_nvwa_trace.py"
SWEEP="${NVWA_EXPERIMENTS_DIR}/dragonfly_trace_sweep.py"

for required_file in "${BIN_CONVERTER}" "${GOAL_CONVERTER}" "${SWEEP}"; do
  if [[ ! -f "${required_file}" ]]; then
    echo "[error] required Nvwa experiment helper not found: ${required_file}" >&2
    exit 1
  fi
done

find_optimized_constructor() {
  local build_examples="${NVWA_ROOT}/build/src/datacenter/examples"
  [[ -d "${build_examples}" ]] || return 1
  find "${build_examples}" -maxdepth 1 -type f -executable -name '*constructor*optimized*' | sort | head -n 1
}

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  if [[ -z "$(find_optimized_constructor || true)" ]]; then
    echo "[build] configuring Nvwa constructor with optimized profile"
    ae_run bash -lc 'cd "${NVWA_ROOT}" && ./ns3 configure --build-profile=optimized --enable-examples --enable-tests'
  fi
  echo "[build] building Nvwa constructor"
  ae_run bash -lc 'cd "${NVWA_ROOT}" && ./ns3 build constructor'
fi

OPTIMIZED_CONSTRUCTOR="$(find_optimized_constructor || true)"
if [[ -z "${OPTIMIZED_CONSTRUCTOR}" ]]; then
  echo "[error] optimized constructor binary not found under ${NVWA_ROOT}/build/src/datacenter/examples" >&2
  echo "[error] run bash scripts/setup_environment.sh, or rerun this script without SKIP_BUILD=1" >&2
  exit 1
fi
echo "optimized_constructor=${OPTIMIZED_CONSTRUCTOR}"

lower_trace="$(printf '%s' "${TRACE_INPUT}" | tr '[:upper:]' '[:lower:]')"
trace_format="${ATLAHS_TRACE_FORMAT:-auto}"
if [[ "${trace_format}" == "auto" ]]; then
  case "${lower_trace}" in
    *.bin) trace_format="bin" ;;
    *.goal) trace_format="goal" ;;
    *.csv) trace_format="csv" ;;
    *)
      echo "[error] cannot infer trace format from ${TRACE_INPUT}" >&2
      echo "[error] set ATLAHS_TRACE_FORMAT to bin, goal, or csv" >&2
      exit 1
      ;;
  esac
fi

TRACE_DIR="${RESULTS_DIR}/traces"
mkdir -p "${TRACE_DIR}"
TRACE_BASENAME="$(basename "${TRACE_INPUT}")"
PREPARED_TRACE="${TRACE_INPUT}"

ATLAHS_HOST_COUNT="${ATLAHS_HOST_COUNT:-}"
ATLAHS_MAP_MODULO_HOSTS="${ATLAHS_MAP_MODULO_HOSTS:-0}"
ATLAHS_CONVERT_MAX_FLOWS="${ATLAHS_CONVERT_MAX_FLOWS:-0}"
ATLAHS_MAX_FLOWS_PER_RANK="${ATLAHS_MAX_FLOWS_PER_RANK:-200}"
ATLAHS_PROGRESS_INTERVAL="${ATLAHS_PROGRESS_INTERVAL:-1000000}"

converter_common_args=()
if [[ -n "${ATLAHS_HOST_COUNT}" ]]; then
  converter_common_args+=(--host-count "${ATLAHS_HOST_COUNT}")
fi
if [[ "${ATLAHS_MAP_MODULO_HOSTS}" == "1" ]]; then
  converter_common_args+=(--map-modulo-hosts)
fi
converter_common_args+=(--max-flows "${ATLAHS_CONVERT_MAX_FLOWS}")

case "${trace_format}" in
  csv)
    PREPARED_TRACE="${TRACE_INPUT}"
    ;;
  bin)
    PREPARED_TRACE="${TRACE_DIR}/${TRACE_BASENAME}.nvwa.csv"
    ATLAHS_SCHEDULE_MODE="${ATLAHS_SCHEDULE_MODE:-loggops}"
    echo "[convert] ATLAHS binary trace -> ${PREPARED_TRACE}"
    ae_run python3 "${BIN_CONVERTER}" \
      -i "${TRACE_INPUT}" \
      -o "${PREPARED_TRACE}" \
      --schedule-mode "${ATLAHS_SCHEDULE_MODE}" \
      "${converter_common_args[@]}" \
      --max-flows-per-rank "${ATLAHS_MAX_FLOWS_PER_RANK}" \
      --progress-interval "${ATLAHS_PROGRESS_INTERVAL}"
    ;;
  goal)
    PREPARED_TRACE="${TRACE_DIR}/${TRACE_BASENAME}.nvwa.csv"
    ATLAHS_SCHEDULE_MODE="${ATLAHS_SCHEDULE_MODE:-dag}"
    echo "[convert] ATLAHS GOAL trace -> ${PREPARED_TRACE}"
    ae_run python3 "${GOAL_CONVERTER}" \
      -i "${TRACE_INPUT}" \
      -o "${PREPARED_TRACE}" \
      --schedule-mode "${ATLAHS_SCHEDULE_MODE}" \
      "${converter_common_args[@]}"
    ;;
  *)
    echo "[error] ATLAHS_TRACE_FORMAT must be auto, bin, goal, or csv; got ${trace_format}" >&2
    exit 1
    ;;
esac

if [[ ! -s "${PREPARED_TRACE}" ]]; then
  echo "[error] prepared Nvwa traffic trace is missing or empty: ${PREPARED_TRACE}" >&2
  exit 1
fi

DRAGONFLY_H_VALUES="${DRAGONFLY_H_VALUES:-auto}"
ROUTINGS="${ROUTINGS:-RuleBased,NodeBfs}"
TRAFFIC_TRACE_MAX_FLOWS="${TRAFFIC_TRACE_MAX_FLOWS:-0}"
TRAFFIC_REPLAY_MODE="${TRAFFIC_REPLAY_MODE:-batch}"
TRAFFIC_TRACE_TIME_SCALE="${TRAFFIC_TRACE_TIME_SCALE:-1.0}"
TRAFFIC_START_OFFSET="${TRAFFIC_START_OFFSET:-1.0}"
TRAFFIC_TRACE_STOP_PADDING="${TRAFFIC_TRACE_STOP_PADDING:-1.0}"
PACKET_SIZE="${PACKET_SIZE:-64000}"
DATA_RATE="${DATA_RATE:-100Gbps}"
BANDWIDTH="${BANDWIDTH:-100Gbps}"
DELAY="${DELAY:-1us}"

cat > "${RESULTS_DIR}/experiment_6_settings.txt" <<EOF
nvwa_root=${NVWA_ROOT}
atlahs_trace=${TRACE_INPUT}
atlahs_trace_url=${ATLAHS_TRACE_URL}
trace_format=${trace_format}
prepared_trace=${PREPARED_TRACE}
atlahs_host_count=${ATLAHS_HOST_COUNT}
atlahs_convert_max_flows=${ATLAHS_CONVERT_MAX_FLOWS}
atlahs_max_flows_per_rank=${ATLAHS_MAX_FLOWS_PER_RANK}
dragonfly_h_values=${DRAGONFLY_H_VALUES}
routings=${ROUTINGS}
traffic_trace_max_flows=${TRAFFIC_TRACE_MAX_FLOWS}
traffic_replay_mode=${TRAFFIC_REPLAY_MODE}
packet_size=${PACKET_SIZE}
data_rate=${DATA_RATE}
bandwidth=${BANDWIDTH}
delay=${DELAY}
optimized_constructor=${OPTIMIZED_CONSTRUCTOR}
EOF

echo "prepared_trace=${PREPARED_TRACE}"
echo "dragonfly_h_values=${DRAGONFLY_H_VALUES}"
echo "routings=${ROUTINGS}"

cd "${NVWA_ROOT}"
ae_run python3 "${SWEEP}" \
  --skip-build \
  --build-profile optimized \
  --h-values "${DRAGONFLY_H_VALUES}" \
  --routings "${ROUTINGS}" \
  --traffic-trace "${PREPARED_TRACE}" \
  --traffic-trace-max-flows "${TRAFFIC_TRACE_MAX_FLOWS}" \
  --traffic-replay-mode "${TRAFFIC_REPLAY_MODE}" \
  --traffic-trace-time-scale "${TRAFFIC_TRACE_TIME_SCALE}" \
  --traffic-start-offset "${TRAFFIC_START_OFFSET}" \
  --traffic-trace-stop-padding "${TRAFFIC_TRACE_STOP_PADDING}" \
  --packet-size "${PACKET_SIZE}" \
  --data-rate "${DATA_RATE}" \
  --bandwidth "${BANDWIDTH}" \
  --delay "${DELAY}" \
  --out-dir "${RESULTS_DIR}" \
  --summary-name "experiment_6.csv"

printf '%s\n' "${RESULTS_DIR}" > "${AE_ROOT}/results/latest_atlahs_dragonfly_production_workload.txt"

cat <<EOF
experiment6_results=${RESULTS_DIR}
experiment_6_summary=${RESULTS_DIR}/experiment_6.csv
experiment6_manifest=${RESULTS_DIR}/manifest.json
EOF
