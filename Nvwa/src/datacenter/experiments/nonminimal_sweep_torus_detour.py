#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    sweep = Path(__file__).resolve().parent / "nonminimal_sweep.py"
    cmd = [sys.executable, str(sweep)] + sys.argv[1:] + ["--only", "torus_detour1,torus_detour2"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
