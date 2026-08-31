#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../../.."

echo "[EXP2] Fattree failure (smoke)"
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --only-k 8 \
  --only-fr 0.001 \
  --resume-policy skip_success

echo "[EXP2] Fattree failure (full)"
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --resume-policy skip_success
