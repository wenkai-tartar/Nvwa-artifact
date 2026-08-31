#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
REQUIRE_BUILD=1

usage() {
  cat <<'EOF'
Usage: scripts/check_environment.sh [--require-build|--no-build-required]

Checks the artifact checkout, system tools, Python plotting dependencies, and
the optimized Nvwa constructor binary produced by scripts/setup_environment.sh.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --require-build)
      REQUIRE_BUILD=1
      ;;
    --no-build-required)
      REQUIRE_BUILD=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

failures=0

ok() {
  echo "[ok] $*"
}

warn() {
  echo "[warn] $*"
}

fail() {
  echo "[error] $*" >&2
  failures=$((failures + 1))
}

check_command() {
  local cmd="$1"
  if command -v "${cmd}" >/dev/null 2>&1; then
    ok "found command: ${cmd}"
  else
    fail "missing command: ${cmd}"
  fi
}

check_file() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    ok "found file: ${path}"
  else
    fail "missing file: ${path}"
  fi
}

check_executable() {
  local path="$1"
  if [[ -x "${path}" ]]; then
    ok "found executable: ${path}"
  else
    fail "missing executable: ${path}"
  fi
}

check_dir() {
  local path="$1"
  if [[ -d "${path}" ]]; then
    ok "found directory: ${path}"
  else
    fail "missing directory: ${path}"
  fi
}

optimized_constructor() {
  local build_examples="${NVWA_ROOT}/build/src/datacenter/examples"
  [[ -d "${build_examples}" ]] || return 1
  find "${build_examples}" -maxdepth 1 -type f -executable -name '*constructor*optimized*' \
    | sort \
    | head -n 1
}

echo "artifact_root=${AE_ROOT}"
echo "nvwa_root=${NVWA_ROOT}"

check_dir "${AE_ROOT}"
check_dir "${NVWA_ROOT}"
check_executable "${NVWA_ROOT}/ns3"
check_file "${AE_ROOT}/README.md"
check_file "${SCRIPT_DIR}/run_helpers.sh"
check_file "${SCRIPT_DIR}/run_suite_helpers.sh"
check_file "${SCRIPT_DIR}/run_lightweight_experiments.sh"
check_file "${SCRIPT_DIR}/run_full_experiments.sh"
check_file "${SCRIPT_DIR}/run_topology_ring_allreduce_stats.py"
check_file "${NVWA_ROOT}/src/datacenter/experiments/fattree_time_profile_sweep.py"
check_file "${NVWA_ROOT}/src/datacenter/examples/inputs/topology_generator.py"
check_file "${AE_ROOT}/plots/plot_figures.sh"
check_dir "${AE_ROOT}/data/experiment_data"
check_dir "${AE_ROOT}/data/archived_paper_data"

for data_file in \
  experiment_1.csv \
  experiment_2_summary.csv \
  experiment_2_memory_profile.csv \
  experiment_2_object_profile.csv \
  experiment_3_summary.csv \
  experiment_3_time_profile.csv \
  experiment_3_time_breakdown.csv \
  experiment_4.csv \
  experiment_5.csv \
  experiment_6.csv \
  experiment_6_manifest.json \
  experiment_7_dragonfly.csv \
  experiment_7_fattree.csv \
  experiment_8.csv \
  experiment_9.csv
do
  check_file "${AE_ROOT}/data/experiment_data/${data_file}"
done

for cmd in bash python3 cmake gcc g++ make git; do
  check_command "${cmd}"
done

if bash -n "${SCRIPT_DIR}"/*.sh "${AE_ROOT}/plots"/*.sh; then
  ok "shell script syntax"
else
  fail "shell script syntax check failed"
fi

if python3 - <<'PY'
import importlib

for module in ("matplotlib", "numpy", "pandas"):
    importlib.import_module(module)
PY
then
  ok "Python modules: matplotlib, numpy, pandas"
else
  fail "missing Python plotting modules; run bash scripts/install_ubuntu_deps.sh"
fi

if PYTHONPATH="${NVWA_ROOT}/src/datacenter/examples/inputs:${NVWA_ROOT}/src/datacenter/experiments:${PYTHONPATH:-}" \
  python3 - <<'PY'
import topology_generator
PY
then
  ok "Nvwa Python helper imports"
else
  fail "cannot import Nvwa Python helpers"
fi

cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
if [[ "${cpu_count}" =~ ^[0-9]+$ && "${cpu_count}" -gt 0 ]]; then
  ok "online CPUs: ${cpu_count}"
  if (( cpu_count < 8 )); then
    warn "recommended artifact-review machine has at least 8 CPU cores"
  fi
else
  warn "could not determine CPU count"
fi

if [[ -r /proc/meminfo ]]; then
  mem_gib="$(awk '/MemTotal/ { printf "%.0f", $2 / 1024 / 1024 }' /proc/meminfo)"
  ok "system memory: ${mem_gib} GiB"
  if [[ "${mem_gib}" =~ ^[0-9]+$ ]] && (( mem_gib < 60 )); then
    warn "recommended artifact-review machine has at least 64GB RAM"
  fi
else
  warn "could not determine system memory"
fi

constructor="$(optimized_constructor || true)"
if [[ -n "${constructor}" ]]; then
  ok "optimized constructor: ${constructor}"
elif [[ "${REQUIRE_BUILD}" == "1" ]]; then
  fail "optimized constructor not found; run bash scripts/setup_environment.sh"
else
  warn "optimized constructor not found; run bash scripts/setup_environment.sh before kick-the-tires or experiments"
fi

if (( failures > 0 )); then
  echo "Environment check failed with ${failures} issue(s)." >&2
  exit 1
fi

echo "Environment check passed."
