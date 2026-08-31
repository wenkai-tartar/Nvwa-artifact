#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


DEFAULT_ONLY = "torus_shortest"
DEFAULT_D = "5,10,15,20"


def _has_flag(name: str) -> bool:
    for arg in sys.argv[1:]:
        if arg == name or arg.startswith(name + "="):
            return True
    return False


def main() -> int:
    sweep = Path(__file__).resolve().parent / "nonminimal_shortest_sweep.py"
    cmd = [sys.executable, str(sweep)] + sys.argv[1:]
    if not _has_flag("--only"):
        cmd += ["--only", DEFAULT_ONLY]
    if not _has_flag("--only-d"):
        cmd += ["--only-d", DEFAULT_D]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
