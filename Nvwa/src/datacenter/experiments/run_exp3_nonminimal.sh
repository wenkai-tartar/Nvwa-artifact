#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../../.."

echo "[EXP3] Non-minimal (smoke)"
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py --skip-build --only-h 2
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py --skip-build --only-h 2
python3 src/datacenter/experiments/nonminimal_sweep_torus_detour.py --skip-build --only-d 5

echo "[EXP3] Non-minimal (full)"
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_torus_detour.py --skip-build
