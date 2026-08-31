#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="${AE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
NVWA_ROOT="${NVWA_ROOT:-${AE_ROOT}/Nvwa}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RESULTS_DIR="${RESULTS_DIR:-${AE_ROOT}/results/setup_${RUN_ID}}"
LOG_DIR="${RESULTS_DIR}/logs"

mkdir -p "${LOG_DIR}"

if [[ ! -d "${NVWA_ROOT}" ]]; then
  echo "[error] Nvwa root not found: ${NVWA_ROOT}" >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "[error] cmake not found; run bash Nvwa-artifact/scripts/install_ubuntu_deps.sh before setup" >&2
  exit 1
fi

export AE_ROOT
export NVWA_ROOT
export RESULTS_DIR
unset CMAKE_GENERATOR

run_step() {
  local name="$1"
  shift
  local log_file="${LOG_DIR}/${name}.log"
  printf '\n==> %s\n' "${name}"
  "$@" 2>&1 | tee "${log_file}"
}

run_step toolchain bash -lc '
  set -euo pipefail
  cmake --version | head -n 1
  gcc --version | head -n 1
  g++ --version | head -n 1
  python3 --version
  git -C "${NVWA_ROOT}" rev-parse HEAD
  git -C "${NVWA_ROOT}" status --short
'

run_step nvwa_configure bash -lc '
  set -euo pipefail
  cd "${NVWA_ROOT}"
  ./ns3 configure --build-profile=optimized --enable-examples --enable-tests
'

run_step nvwa_build bash -lc '
  set -euo pipefail
  cd "${NVWA_ROOT}"
  ./ns3 build
'

run_step nvwa_smoke bash -lc '
  set -euo pipefail
  cd "${NVWA_ROOT}"
  ./ns3 run simple-global-routing
'

cat <<EOF

Environment setup completed.
results_dir=${RESULTS_DIR}
logs_dir=${LOG_DIR}
EOF
