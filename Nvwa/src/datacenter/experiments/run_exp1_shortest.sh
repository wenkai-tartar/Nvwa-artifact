#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../../.."

echo "[EXP1] Fattree shortest (smoke)"
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-k 8

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-k 8

echo "[EXP1] Fattree shortest (full)"
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing RuleBased

echo "[EXP1] Dragonfly shortest (smoke)"
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-h 2

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-h 2

echo "[EXP1] Dragonfly shortest (full)"
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased

echo "[EXP1] Torus shortest (smoke)"
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-d 2

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-d 2

echo "[EXP1] Torus shortest (full)"
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
