#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  git curl build-essential gcc g++ make pkg-config \
  python3 python3-dev python3-pip python3-venv \
  python3-matplotlib python3-pandas \
  cmake \
  libsqlite3-dev libxml2-dev libgtk-3-dev libboost-all-dev

cmake --version | head -n 1
