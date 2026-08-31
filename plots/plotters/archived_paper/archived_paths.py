#!/usr/bin/env python3
"""Shared paths for the archived paper plotting scripts."""

from __future__ import annotations

import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AE_ROOT = SCRIPT_DIR.parents[2]

DATA_DIR = Path(
    os.environ.get("ARCHIVED_DATA_DIR", str(AE_ROOT / "data" / "archived_paper_data"))
).resolve()
OUT_DIR = Path(
    os.environ.get("OUT_DIR", str(AE_ROOT / "results" / "full_data_figures"))
).resolve()


def data_path(name: str) -> Path:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"archived data file not found: {path}")
    return path


def ensure_output_dir() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR


def output_path(name: str) -> Path:
    return ensure_output_dir() / name
