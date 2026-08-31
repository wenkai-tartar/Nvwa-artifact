#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# NSDI'26 Nvwa orchestrator (auto-detect build tool: ./ns3 | ./ns | ./waf)
# + NUMA-aware scheduling (optional via --numa-aware)

import argparse
import csv
import datetime
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import functools, builtins, sys
print = functools.partial(builtins.print, flush=True)
sys.stdout.reconfigure(line_buffering=True)

import fcntl  # NEW: for non-blocking stdout

RESULTS_DIR = Path('results')
RESULTS_DIR.mkdir(exist_ok=True)

RE_INIT_TIME = re.compile(r'\bInitialization\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b', re.I)
RE_LOOK = re.compile(r'\bLookup\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b', re.I)
RE_EXEC_TIME = re.compile(r'\bExecution\s*time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*s\b', re.I)
RE_PEAK = re.compile(r'\bPeak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b', re.I)
RE_ROUTING = re.compile(r'\bRouting algorithm\s*:\s*([^\s]+)\b', re.I)
RE_INIT_MEMORY = re.compile(r'\bInitialization\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b', re.I)
RE_EXEC_MEMORY = re.compile(r'\bExecution\s*peak\s*memory\s*usage\s*=\s*([0-9]+)\s*KB\b', re.I)
RE_INIT_MEMORY_PROFILE = re.compile(
    r'\bInitialization\s*memory\s*profile:\s*'
    r'stage=([^\s]+)\s+category=([^\s]+)\s+rss=([-0-9]+)\s*KB\s+'
    r'delta=([-0-9]+)\s*KB\s+share=([0-9]+(?:\.[0-9]+)?)%\s+detail=(.*)$',
    re.I,
)
RE_INIT_MEMORY_PROFILE_SUMMARY = re.compile(
    r'\bInitialization\s*memory\s*profile\s*summary:\s*(.*)$',
    re.I,
)
RE_INIT_OBJECT_PROFILE = re.compile(
    r'\bInitialization\s*object\s*profile:\s*(.*)$',
    re.I,
)
# Perf cache metrics regex patterns
RE_CACHE_REFERENCES = re.compile(r'\s*([0-9,]+)\s+cache-references\b', re.I)
RE_CACHE_MISSES     = re.compile(r'\s*([0-9,]+)\s+cache-misses\b', re.I)

@dataclass
class ExpArgs:
    config: Optional[str] = None
    topo: Optional[str] = None
    routing: Optional[str] = None
    dataSize: Optional[int] = None
    degree: Optional[int] = None
    memory: bool = False
    extra: Dict[str, str] = field(default_factory=dict)

    def to_prog_arg_list(self) -> List[str]:
        args = []
        cfg = self.config or self.topo
        if cfg is not None:
            args += [f'--config={cfg}']
        if self.routing is not None:
            args += [f'--routing={self.routing}']
        if self.dataSize is not None:
            args += [f'--dataSize={self.dataSize}']
        if self.degree is not None:
            args += [f'--degree={self.degree}']
        if self.memory:
            args += ['--memory=true']
        for k, v in self.extra.items():
            args += [f'--{k}={v}']
        return ['constructor'] + args

@dataclass
class Experiment:
    name: str
    args: ExpArgs
    use_perf: bool = False

@dataclass
class SetSpec:
    name: str
    build_profile: str = 'release'
    enable_examples: bool = True
    experiments: List[Experiment] = field(default_factory=list)

def build_experiment_sets() -> Dict[str, SetSpec]:
    sets: Dict[str, SetSpec] = {}

    sets['fattree_time_and_mem'] = SetSpec(
        name='fattree_time_and_mem',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('fattree-mem-ft-k8-rb-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k8-bfs-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k8-glo-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k16-rb-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k16-bfs-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k16-glo-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k24-rb-ar-1MB', ExpArgs(config='fattree_k24_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k24-bfs-ar-1MB', ExpArgs(config='fattree_k24_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            Experiment('fattree-mem-ft-k24-glo-ar-1MB', ExpArgs(config='fattree_k24_100g_1u.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k32-rb-ar-1MB', ExpArgs(config='fattree_k32_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k32-bfs-ar-1MB', ExpArgs(config='fattree_k32_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k40-rb-ar-1MB', ExpArgs(config='fattree_k40_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k40-bfs-ar-1MB', ExpArgs(config='fattree_k40_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k48-rb-ar-1MB', ExpArgs(config='fattree_k48_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k48-bfs-ar-1MB', ExpArgs(config='fattree_k48_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k56-rb-ar-1MB', ExpArgs(config='fattree_k56_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k56-bfs-ar-1MB', ExpArgs(config='fattree_k56_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k64-rb-ar-1MB', ExpArgs(config='fattree_k64_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k64-bfs-ar-1MB', ExpArgs(config='fattree_k64_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k72-rb-ar-1MB', ExpArgs(config='fattree_k72_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k80-rb-ar-1MB', ExpArgs(config='fattree_k80_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k88-rb-ar-1MB', ExpArgs(config='fattree_k88_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-mem-ft-k96-rb-ar-1MB', ExpArgs(config='fattree_k96_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true'))
            Experiment('fattree-mem-ft-k8-rb-aa-400KB',   ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k8-bfs-aa-400KB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k8-glo-aa-400KB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='Global',    degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k16-rb-aa-400KB',  ExpArgs(config='fattree_k16_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k16-bfs-aa-400KB', ExpArgs(config='fattree_k16_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k16-glo-aa-400KB', ExpArgs(config='fattree_k16_100g_1u.json', routing='Global',    degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k24-rb-aa-400KB',  ExpArgs(config='fattree_k24_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k24-bfs-aa-400KB', ExpArgs(config='fattree_k24_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k24-glo-aa-400KB', ExpArgs(config='fattree_k24_100g_1u.json', routing='Global',    degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k32-rb-aa-400KB',  ExpArgs(config='fattree_k32_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k32-bfs-aa-400KB', ExpArgs(config='fattree_k32_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k40-rb-aa-400KB',  ExpArgs(config='fattree_k40_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k40-bfs-aa-400KB', ExpArgs(config='fattree_k40_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k48-rb-aa-400KB',  ExpArgs(config='fattree_k48_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k48-bfs-aa-1MB', ExpArgs(config='fattree_k48_100g_1u.json', routing='NodeBfs',     degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k56-rb-aa-400KB',  ExpArgs(config='fattree_k56_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k56-bfs-aa-400KB', ExpArgs(config='fattree_k56_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            Experiment('fattree-mem-ft-k64-rb-aa-400KB',  ExpArgs(config='fattree_k64_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            # Experiment('fattree-mem-ft-k64-bfs-aa-400KB', ExpArgs(config='fattree_k64_100g_1u.json', routing='NodeBfs',   degree=8, dataSize=409600, memory='true')),
            # Experiment('fattree-mem-ft-k72-rb-aa-400KB',  ExpArgs(config='fattree_k72_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            # Experiment('fattree-mem-ft-k80-rb-aa-400KB',  ExpArgs(config='fattree_k80_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            # Experiment('fattree-mem-ft-k88-rb-aa-400KB',  ExpArgs(config='fattree_k88_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true')),
            # Experiment('fattree-mem-ft-k96-rb-aa-400KB',  ExpArgs(config='fattree_k96_100g_1u.json', routing='RuleBased', degree=8, dataSize=409600, memory='true'))
        ]
    )

    sets['fattree_workload'] = SetSpec(
        name='ffattree_workload',
        build_profile='release',
        enable_examples=True,
        experiments=[
            Experiment('fattree-k8-rb-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('fattree-k8-bfs-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            Experiment('fattree-k8-rb-ar-8MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=8388608, memory='true')),
            Experiment('fattree-k8-bfs-ar-8MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=8388608, memory='true')),
            Experiment('fattree-k8-rb-ar-16MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=16777216, memory='true')),
            Experiment('fattree-k8-bfs-ar-16MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=16777216, memory='true')),
            Experiment('fattree-k8-rb-ar-64MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=67108864, memory='true')),
            Experiment('fattree-k8-bfs-ar-64MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=67108864, memory='true')),
            Experiment('fattree-k8-rb-ar-128MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=134217728, memory='true')),
            Experiment('fattree-k8-bfs-ar-128MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=134217728, memory='true')),
            # Experiment('fattree-k8-glo-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-k16-rb-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-k16-bfs-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-k16-glo-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
        ]
    )

    sets['fattree_perf'] = SetSpec(
        name='fattree_perf',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('fattree-perf-k8-rb-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k8-bfs-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k8-glo-ar-1MB',  ExpArgs(config='fattree_k8_100g_1u.json',  routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k16-rb-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k16-bfs-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k16-glo-ar-1MB', ExpArgs(config='fattree_k16_100g_1u.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k24-rb-ar-1MB', ExpArgs(config='fattree_k24_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k24-bfs-ar-1MB', ExpArgs(config='fattree_k24_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k32-rb-ar-1MB', ExpArgs(config='fattree_k32_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k32-bfs-ar-1MB', ExpArgs(config='fattree_k32_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k40-rb-ar-1MB', ExpArgs(config='fattree_k40_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k40-bfs-ar-1MB', ExpArgs(config='fattree_k40_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k48-rb-ar-1MB', ExpArgs(config='fattree_k48_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('fattree-perf-k48-bfs-ar-1MB', ExpArgs(config='fattree_k48_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
            Experiment('fattree-perf-k56-rb-ar-1MB', ExpArgs(config='fattree_k56_100g_1u.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('fattree-perf-k56-bfs-ar-1MB', ExpArgs(config='fattree_k56_100g_1u.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')),
        ]
    )

    sets['torus_time_and_mem'] = SetSpec(
        name='torus_time_and_mem',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('torus-mem-x2-y2-z2-rb-ar-1MB', ExpArgs(config='torus-x2-y2-z2.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x2-y2-z2-bfs-ar-1MB', ExpArgs(config='torus-x2-y2-z2.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('torus-mem-x5-y5-z5-glo-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x5-y5-z5-rb-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x5-y5-z5-bfs-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x6-y6-z6-rb-ar-1MB', ExpArgs(config='torus-x6-y6-z6.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x6-y6-z6-bfs-ar-1MB', ExpArgs(config='torus-x6-y6-z6.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x10-y10-z10-rb-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x10-y10-z10-bfs-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x10-y10-z10-gl-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x15-y15-z15-rb-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x15-y15-z15-bfs-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x15-y15-z15-gl-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x20-y20-z20-rb-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x20-y20-z20-bfs-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x20-y20-z20-gl-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x25-y25-z25-rb-ar-1MB', ExpArgs(config='torus-x25-y25-z25.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x25-y25-z25-bfs-ar-1MB', ExpArgs(config='torus-x25-y25-z25.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x30-y30-z30-rb-ar-1MB', ExpArgs(config='torus-x30-y30-z30.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x30-y30-z30-bfs-ar-1MB', ExpArgs(config='torus-x30-y30-z30.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x40-y40-z40-rb-ar-1MB', ExpArgs(config='torus-x40-y40-z40.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x50-y50-z50-rb-ar-1MB', ExpArgs(config='torus-x50-y50-z50.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x40-y40-z40-bfs-ar-1MB', ExpArgs(config='torus-x40-y40-z40.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-mem-x50-y50-z50-bfs-ar-1MB', ExpArgs(config='torus-x50-y50-z50.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true'))
        ]
    )

    sets['torus_perf'] = SetSpec(
        name='torus_perf',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('torus-perf-x5-y5-z5-glo-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x5-y5-z5-rb-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x5-y5-z5-bfs-ar-1MB', ExpArgs(config='torus-x5-y5-z5.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x10-y10-z10-rb-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x10-y10-z10-bfs-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x10-y10-z10-gl-ar-1MB', ExpArgs(config='torus-x10-y10-z10.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            Experiment('torus-perf-x15-y15-z15-rb-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('torus-perf-x15-y15-z15-bfs-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            Experiment('torus-perf-x15-y15-z15-gl-ar-1MB', ExpArgs(config='torus-x15-y15-z15.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x20-y20-z20-rb-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x20-y20-z20-bfs-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x20-y20-z20-gl-ar-1MB', ExpArgs(config='torus-x20-y20-z20.json', routing='Global', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x25-y25-z25-rb-ar-1MB', ExpArgs(config='torus-x25-y25-z25.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x25-y25-z25-bfs-ar-1MB', ExpArgs(config='torus-x25-y25-z25.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x30-y30-z30-rb-ar-1MB', ExpArgs(config='torus-x30-y30-z30.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('torus-perf-x30-y30-z30-bfs-ar-1MB', ExpArgs(config='torus-x30-y30-z30.json', routing='NodeBfsWithHost', degree=4, dataSize=1048576, memory='true'))
        ]
    )

    sets['dragonfly_time_and_mem'] = SetSpec(
        name='dragonfly_time_and_mem',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('dragonfly-h2-rb-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-h2-bfs-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h2-glo-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-h4-rb-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('dragonfly-h4-bfs-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-h4-glo-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h6-rb-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-h6-bfs-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h6-glo-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-h8-rb-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('dragonfly-h8-bfs-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h8-glo-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h10-rb-ar-1MB', ExpArgs(config='dragonfly_h10.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-h10-bfs-ar-1MB', ExpArgs(config='dragonfly_h10.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h12-rb-ar-1MB', ExpArgs(config='dragonfly_h12.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-h12-bfs-ar-1MB', ExpArgs(config='dragonfly_h12.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-h14-rb-ar-1MB', ExpArgs(config='dragonfly_h14.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-h14-bfs-ar-1MB', ExpArgs(config='dragonfly_h14.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
        ]
    )

    sets['dragonfly_perf'] = SetSpec(
        name='dragonfly_perf',
        build_profile='release',
        enable_examples=True,
        experiments=[
            # Experiment('dragonfly-perf-h2-rb-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-perf-h2-bfs-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h2-glo-ar-1MB', ExpArgs(config='dragonfly_h2.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-perf-h4-rb-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('dragonfly-perf-h4-bfs-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h4-glo-ar-1MB', ExpArgs(config='dragonfly_h4.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h6-rb-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-perf-h6-bfs-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h6-glo-ar-1MB', ExpArgs(config='dragonfly_h6.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-perf-h8-rb-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('dragonfly-perf-h8-bfs-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h8-glo-ar-1MB', ExpArgs(config='dragonfly_h8.json', routing='Global', degree=4, dataSize=1048576, memory='true')), 
            Experiment('dragonfly-perf-h10-rb-ar-1MB', ExpArgs(config='dragonfly_h10.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            Experiment('dragonfly-perf-h10-bfs-ar-1MB', ExpArgs(config='dragonfly_h10.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h12-rb-ar-1MB', ExpArgs(config='dragonfly_h12.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
            # Experiment('dragonfly-perf-h12-bfs-ar-1MB', ExpArgs(config='dragonfly_h12.json', routing='NodeBfs', degree=4, dataSize=1048576, memory='true')), 
            # Experiment('dragonfly-perf-h14-rb-ar-1MB', ExpArgs(config='dragonfly_h14.json', routing='RuleBased', degree=4, dataSize=1048576, memory='true')),
        ]
    )

    return sets

def parse_cores(cores_str: Optional[str]) -> List[int]:
    if not cores_str:
        try:
            cores = sorted(os.sched_getaffinity(0))
            return list(cores)
        except Exception:
            from multiprocessing import cpu_count
            return list(range(cpu_count()))
    cores: List[int] = []
    for part in cores_str.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            cores.extend(range(int(a), int(b) + 1))
        else:
            cores.append(int(part))
    return sorted(set(cores))

def timestamp() -> str:
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

def _read_meminfo() -> Tuple[int, int]:
    total = avail = None
    with open('/proc/meminfo', 'r') as f:
        for line in f:
            if line.startswith('MemTotal:'):
                total = int(line.split()[1])
            elif line.startswith('MemAvailable:'):
                avail = int(line.split()[1])
            if total is not None and avail is not None:
                break
    if total is None or avail is None:
        raise RuntimeError('Cannot read MemTotal/MemAvailable from /proc/meminfo')
    return total, avail

def mem_status() -> Dict[str, float]:
    total_kb, avail_kb = _read_meminfo()
    used_kb = total_kb - avail_kb
    used_pct = used_kb / total_kb * 100.0
    avail_gb = avail_kb / (1024.0 * 1024.0)
    return {'used_pct': used_pct, 'avail_gb': avail_gb}

def mem_ok(thresh_pct: Optional[float], min_free_gb: Optional[float]) -> Tuple[bool, Dict[str, float]]:
    s = mem_status()
    ok_pct = True if thresh_pct is None else (s['used_pct'] < float(thresh_pct))
    ok_free = True if min_free_gb is None else (s['avail_gb'] >= float(min_free_gb))
    return (ok_pct and ok_free), s

# ---- Build tool detection ----
def _is_exe(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)

def pick_build_tool() -> Tuple[str, str]:
    """
    Return (tool, kind) where:
      kind in {'ns3', 'ns', 'waf'}
      tool is the executable path './ns3' or './ns' or './waf'
    Preference: ns3 > ns > waf
    """
    if _is_exe('./ns3'):
        return './ns3', 'ns3'
    if _is_exe('./ns'):
        return './ns', 'ns'
    if _is_exe('./waf'):
        return './waf', 'waf'
    raise SystemExit("No build tool found. Expected one of: ./ns3, ./ns, or ./waf in repo root.")

def run_cmd_logged(cmd: List[str], logfile: Path, cwd: Optional[str] = None) -> int:
    with open(logfile, 'a') as lf:
        lf.write(f"$ {shlex.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            lf.write(line)
        rc = proc.wait()
        lf.write(f"\n[rc={rc}] {shlex.join(cmd)}\n")
        lf.flush()
    return rc

def ns_configure_and_build(setname: str, build_profile: str, enable_examples: bool) -> None:
    ts = timestamp()
    log = RESULTS_DIR / f'build-{setname}-{build_profile}-{ts}.log'
    tool, kind = pick_build_tool()
    print(f"[BUILD] Using {tool} ({kind}) for set='{setname}' profile='{build_profile}' examples={'on' if enable_examples else 'off'}")
    if kind in ('ns3', 'ns'):
        cfg_cmd = [tool, 'configure', f'--build-profile={build_profile}']
        if enable_examples:
            cfg_cmd.append('--enable-examples')
        rc = run_cmd_logged(cfg_cmd, log)
        if rc != 0:
            raise SystemExit(f"{tool} configure failed with rc={rc}. See log: {log}")
        bld_cmd = [tool, 'build']
        rc = run_cmd_logged(bld_cmd, log)
        if rc != 0:
            raise SystemExit(f"{tool} build failed with rc={rc}. See log: {log}")
    else:  # waf
        waf_cfg = [tool, 'configure', f'--build-profile={build_profile}']
        if enable_examples:
            waf_cfg.append('--enable-examples')
        rc = run_cmd_logged(waf_cfg, log)
        if rc != 0:
            raise SystemExit(f"{tool} configure failed with rc={rc}. See log: {log}")
        rc = run_cmd_logged([tool, 'build'], log)
        if rc != 0:
            raise SystemExit(f"{tool} build failed with rc={rc}. See log: {log}")
    print(f"[BUILD] Done. Log: {log}")

# ---- NUMA helpers ----
def detect_numa_topology() -> Dict[int, List[int]]:
    """
    Return {node_id: [cpu ids]} using /sys/devices/system/node/node*/cpulist.
    If sysfs not present, return {}.
    """
    nodes: Dict[int, List[int]] = {}
    sysfs = Path('/sys/devices/system/node')
    if not sysfs.exists():
        return nodes
    for node_dir in sysfs.glob('node[0-9]*'):
        try:
            node_id = int(node_dir.name.replace('node', ''))
        except ValueError:
            continue
        cpulist_file = node_dir / 'cpulist'
        if cpulist_file.exists():
            text = cpulist_file.read_text().strip()
            cores: List[int] = []
            if text:
                for part in text.split(','):
                    part = part.strip()
                    if '-' in part:
                        a, b = part.split('-', 1)
                        cores.extend(range(int(a), int(b) + 1))
                    else:
                        cores.append(int(part))
            nodes[node_id] = cores
    return nodes

@dataclass
class ProcRecord:
    exp: Experiment
    core: int
    popen: subprocess.Popen
    t_start: float
    log_file: Path
    cmd_file: Path
    perf_file: Optional[Path] = None
    numa_node: Optional[int] = None

def ns3_command(exp: Experiment, core: int, numa_node: Optional[int] = None) -> Tuple[List[str], Path, Path, Optional[Path]]:
    ts = timestamp()
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', exp.name)
    log_file = RESULTS_DIR / f'{safe_name}-{ts}.log'
    cmd_file = RESULTS_DIR / f'{safe_name}-{ts}.sh'
    perf_file = RESULTS_DIR / f'perf-{safe_name}-{ts}.txt' if exp.use_perf else None

    prog_args = exp.args.to_prog_arg_list()
    prog_str = ' '.join(prog_args)

    # Use numactl if a NUMA node is specified; otherwise fallback to taskset
    if numa_node is not None:
        cmd_core = ['numactl', f'--cpunodebind={numa_node}', f'--membind={numa_node}', f'--physcpubind={core}']
    else:
        cmd_core = ['taskset', '-c', str(core)]

    # NEW: enforce line-buffered stdio to improve real-time logging
    bufwrap = ['stdbuf', '-oL', '-eL']

    run_tool, _ = pick_build_tool()
    base = cmd_core + bufwrap + [run_tool, 'run', prog_str]

    if exp.use_perf:
        cmd = cmd_core + bufwrap + ['perf', 'stat',
               '-e', 'cache-references,cache-misses',
               '-o', str(perf_file), '--', run_tool, 'run', prog_str]
    else:
        cmd = base

    with open(cmd_file, 'w') as f:
        f.write('#!/bin/bash\nset -euo pipefail\n')
        f.write(shlex.join(cmd) + '\n')
    cmd_file.chmod(0o755)
    return cmd, log_file, cmd_file, perf_file

def _parse_kv_tokens(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for token in text.strip().split():
        if '=' not in token:
            continue
        key, value = token.split('=', 1)
        values[key] = value
    return values

def parse_stdout_line(line: str, agg: Dict[str, Any]):
    if (m := RE_INIT_TIME.search(line)): agg['init_s'] = float(m.group(1))
    if (m := RE_LOOK.search(line)): agg['lookup_s'] = float(m.group(1))
    if (m := RE_EXEC_TIME.search(line)): agg['exec_s'] = float(m.group(1))
    if (m := RE_INIT_MEMORY.search(line)): agg['init_mem_kb'] = float(m.group(1))
    if (m := RE_EXEC_MEMORY.search(line)): agg['exec_mem_kb'] = float(m.group(1))
    if (m := RE_ROUTING.search(line)): agg['routing'] = m.group(1)
    if (m := RE_INIT_MEMORY_PROFILE_SUMMARY.search(line)):
        agg['_memory_profile_summary'] = _parse_kv_tokens(m.group(1))
    if (m := RE_INIT_MEMORY_PROFILE.search(line)):
        agg.setdefault('_memory_profile', []).append({
            'stage': m.group(1),
            'category': m.group(2),
            'rss_kb': int(m.group(3)),
            'delta_kb': int(m.group(4)),
            'share_pct': float(m.group(5)),
            'detail': m.group(6).strip(),
        })
    if (m := RE_INIT_OBJECT_PROFILE.search(line)):
        agg.setdefault('_object_profile', []).append(_parse_kv_tokens(m.group(1)))

    convert_memory_units(agg)

def convert_memory_units(agg: Dict[str, Any]) -> None:
    """
    Convert memory units from KB to GB
    """
    if 'init_mem_kb' in agg:
        agg['init_mem_gb'] = agg['init_mem_kb'] / (1024.0 * 1024.0)
    if 'exec_mem_kb' in agg:
        agg['exec_mem_gb'] = agg['exec_mem_kb'] / (1024.0 * 1024.0)

def run_one(exp: Experiment, core: int) -> Tuple[int, Dict[str, Any], Optional[Path]]:
    cmd, log_file, cmd_file, perf_file = ns3_command(exp, core, None)
    agg: Dict[str, Any] = {}
    t0 = time.time()
    with open(log_file, 'w') as lf:
        lf.write(f"[START {time.strftime('%F %T')}] core={core} (single-run)\n")
        lf.write(f"$ {shlex.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        # non-blocking
        fd = proc.stdout.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        buf = ''
        while True:
            rc = proc.poll()
            try:
                chunk = proc.stdout.read()
            except Exception:
                chunk = ''
            if chunk:
                buf += chunk
                lines = buf.splitlines(keepends=True)
                if not buf.endswith('\n'):
                    buf = lines[-1]
                    lines = lines[:-1]
                else:
                    buf = ''
                for ln in lines:
                    lf.write(ln)
                    parse_stdout_line(ln, agg)
                lf.flush()
            if rc is not None:
                break
            time.sleep(0.05)
        # flush leftover
        if buf:
            lf.write(buf)
            for ln in buf.splitlines():
                parse_stdout_line(ln, agg)
            lf.flush()
    wall = time.time() - t0
    agg.setdefault('wall_s', wall)
    rc = proc.returncode
    convert_memory_units(agg)
    return rc, agg, perf_file

def parse_perf_file(perf_file_path: Path) -> Dict[str, float]:
    """
    Parse perf stat output file and extract cache-related metrics.
    
    Returns a dictionary with cache metrics:
    - cache_references: Cache references count
    - cache_misses: Cache misses count
    """
    metrics = {}
    
    if not perf_file_path.exists():
        return metrics
    
    try:
        with open(perf_file_path, 'r') as f:
            for line in f:
                # Remove commas from numbers and convert to int
                def clean_number(num_str: str) -> int:
                    return int(num_str.replace(',', ''))
                
                if (m := RE_CACHE_REFERENCES.search(line)):
                    metrics['cache_references'] = clean_number(m.group(1))
                elif (m := RE_CACHE_MISSES.search(line)):
                    metrics['cache_misses'] = clean_number(m.group(1))
    
    except Exception as e:
        print(f"[WARN ] Failed to parse perf file {perf_file_path}: {e}")
    
    return metrics

def cache_miss_rate(agg: Dict[str, Union[int, float]]) -> None:
    refs = agg.get('cache_references')
    misses = agg.get('cache_misses')
    if isinstance(refs, (int, float)) and isinstance(misses, (int, float)) and refs > 0:
        agg['cache_miss_rate'] = misses / refs

# NEW: non-blocking stdout drain helper
def _set_nonblock(pipe):
    if not pipe:
        return
    fd = pipe.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def _drain_stdout_nonblock(proc: subprocess.Popen, log_path: Path, agg: Dict[str, Any]) -> None:
    if not proc.stdout:
        return
    try:
        chunk = proc.stdout.read()
    except Exception:
        return
    if not chunk:
        return
    buf = getattr(proc, '_nvwa_buf', '')
    buf += chunk
    lines = buf.splitlines(keepends=True)
    if not buf.endswith('\n') and lines:
        buf = lines[-1]
        lines = lines[:-1]
    else:
        buf = ''
    if lines:
        with open(log_path, 'a') as lf:
            for ln in lines:
                lf.write(ln)
                parse_stdout_line(ln, agg)
    setattr(proc, '_nvwa_buf', buf)

def orchestrate(exps: List[Experiment], cores: List[int], max_parallel: Optional[int],
                summary_prefix: str,
                mem_thresh_pct: Optional[float] = None,
                mem_min_free_gb: Optional[float] = None,
                mem_poll_interval: float = 1.0,
                numa_aware: bool = False):
    if max_parallel is None or max_parallel <= 0:
        max_parallel = len(cores)
    worker_cores = cores[:max_parallel]

    # NUMA detection (optional)
    numa_map: Optional[Dict[int, List[int]]] = None
    if numa_aware:
        numa_map = detect_numa_topology()
        if not numa_map:
            print("[NUMA ] No NUMA topology detected; falling back to taskset.")
            numa_map = None
        else:
            summary = ", ".join(f"node{nid}:{len(cpus)}cpus" for nid, cpus in sorted(numa_map.items()))
            print(f"[NUMA ] Detected: {summary}")

    # Prepare CSV
    ts = timestamp()
    summary_csv = RESULTS_DIR / f'{summary_prefix}-{ts}.csv'
    memory_profile_csv = RESULTS_DIR / f'{summary_prefix}-memory-profile-{ts}.csv'
    object_profile_csv = RESULTS_DIR / f'{summary_prefix}-object-profile-{ts}.csv'
    with open(summary_csv, 'w', newline='') as csvfile, \
         open(memory_profile_csv, 'w', newline='') as mem_csvfile, \
         open(object_profile_csv, 'w', newline='') as obj_csvfile:
        w = csv.writer(csvfile)
        mem_w = csv.writer(mem_csvfile)
        obj_w = csv.writer(obj_csvfile)
        w.writerow(['name', 'core', 'rc', 'routing', 'init_s', 'lookup_s', 'exec_s', 'wall_s', 'init_peak_mem_gb', 'exec_peak_mem_gb', 'cache_references', 'cache_misses', 'cache_miss_rate', 'perf_file'])
        mem_w.writerow(['name', 'core', 'routing', 'stage', 'category', 'rss_kb', 'delta_kb', 'share_pct', 'detail', 'pid', 'start_rss_kb', 'final_rss_kb', 'total_delta_kb', 'positive_delta_kb', 'samples'])
        obj_w.writerow(['name', 'core', 'routing', 'stage', 'levels', 'nodes', 'netdevices', 'p2p_netdevices', 'channels', 'ipv4', 'ipv4_interfaces', 'routing_protocols', 'rule_based_protocols', 'node_bfs_protocols', 'rule_based_rules', 'routing_entries', 'applications'])

        pending = exps.copy()
        running: Dict[int, ProcRecord] = {}
        finished = 0
        total = len(exps)

        def core_to_numa(core_id: int) -> Optional[int]:
            if not numa_map:
                return None
            for nid, cores_in in numa_map.items():
                if core_id in cores_in:
                    return nid
            return None

        def try_start_next_on(core_id: int) -> bool:
            nonlocal pending
            if not pending:
                return False
            ok, s = mem_ok(mem_thresh_pct, mem_min_free_gb)
            if not ok:
                print(f"[PAUSE] Memory guard active: used={s['used_pct']:.1f}%  avail={s['avail_gb']:.1f}GB "
                      f"(thr={mem_thresh_pct or '-'}% / min_free={mem_min_free_gb or '-'}GB).")
                return False
            exp = pending.pop(0)
            node = core_to_numa(core_id)
            cmd, log_file, cmd_file, perf_file = ns3_command(exp, core_id, node)
            try:
                popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                # pre-create log header
                with open(log_file, 'a') as lf:
                    lf.write(f"[START {time.strftime('%F %T')}] core={core_id} pid={popen.pid}" + (f" numa={node}\n" if node is not None else "\n"))
                    lf.write(f"$ {shlex.join(cmd)}\n")
                # set non-blocking stdout
                _set_nonblock(popen.stdout)
                setattr(popen, '_nvwa_buf', '')
                rec = ProcRecord(exp=exp, core=core_id, popen=popen, t_start=time.time(),
                                 log_file=log_file, cmd_file=cmd_file, perf_file=perf_file, numa_node=node)
                running[core_id] = rec
                if node is not None:
                    print(f'[START] core={core_id:>2} numa={node} name={exp.name} pid={popen.pid}')
                else:
                    print(f'[START] core={core_id:>2} name={exp.name} pid={popen.pid}')
                return True
            except (OSError, subprocess.SubprocessError) as e:
                print(f"[ERROR] Failed to start experiment '{exp.name}' on core {core_id}: {e}")
                # put back and retry later
                pending.insert(0, exp)
                return False
            except Exception as e:
                print(f"[ERROR] Unexpected error starting experiment '{exp.name}' on core {core_id}: {e}")
                pending.insert(0, exp)
                return False

        # Initial dispatch (do not break on one failure; keep trying other cores)
        for c in worker_cores:
            if not try_start_next_on(c):
                continue


        last_stat = None
        # Live loop
        while running or pending:
            idle_cores = []
            to_remove = []
            for core_id, rec in list(running.items()):
                proc = rec.popen
                agg = getattr(proc, '_nvwa_agg', None)
                if agg is None:
                    agg = {}
                    setattr(proc, '_nvwa_agg', agg)

                # Non-blocking drain
                _drain_stdout_nonblock(proc, rec.log_file, agg)

                rc = proc.poll()

                if rc is not None:
                    # Final drain + flush leftover buffer
                    _drain_stdout_nonblock(proc, rec.log_file, agg)
                    leftover = getattr(proc, '_nvwa_buf', '')
                    if leftover:
                        with open(rec.log_file, 'a') as lf:
                            lf.write(leftover)
                        for ln in leftover.splitlines():
                            parse_stdout_line(ln, agg)
                        setattr(proc, '_nvwa_buf', '')

                    wall = time.time() - rec.t_start
                    agg.setdefault('wall_s', wall)
                    
                    # Parse perf and compute miss rate
                    perf_metrics = {}
                    if rec.perf_file and rec.perf_file.exists():
                        perf_metrics = parse_perf_file(rec.perf_file)
                    agg.update(perf_metrics)
                    cache_miss_rate(agg)
                    
                    if rec.numa_node is not None:
                        print(f'[DONE ] core={core_id:>2} numa={rec.numa_node} name={rec.exp.name} rc={rc} wall={wall:.2f}s')
                    else:
                        print(f'[DONE ] core={core_id:>2} name={rec.exp.name} rc={rc} wall={wall:.2f}s')
                    w.writerow([rec.exp.name, core_id, rc, agg.get('routing', ''),
                                agg.get('init_s', ''), agg.get('lookup_s', ''), agg.get('exec_s', ''),
                                agg.get('wall_s', ''), agg.get('init_mem_gb', ''), agg.get('exec_mem_gb', ''),
                                agg.get('cache_references', ''), agg.get('cache_misses', ''), agg.get('cache_miss_rate', ''),
                                str(rec.perf_file) if rec.perf_file else ''])
                    summary = agg.get('_memory_profile_summary', {})
                    if not isinstance(summary, dict):
                        summary = {}
                    for row in agg.get('_memory_profile', []):
                        if not isinstance(row, dict):
                            continue
                        mem_w.writerow([
                            rec.exp.name, core_id, agg.get('routing', ''),
                            row.get('stage', ''), row.get('category', ''),
                            row.get('rss_kb', ''), row.get('delta_kb', ''),
                            row.get('share_pct', ''), row.get('detail', ''),
                            summary.get('pid', ''), summary.get('start_rss', ''),
                            summary.get('final_rss', ''), summary.get('total_delta', ''),
                            summary.get('positive_delta', ''), summary.get('samples', ''),
                        ])
                    for row in agg.get('_object_profile', []):
                        if not isinstance(row, dict):
                            continue
                        obj_w.writerow([
                            rec.exp.name, core_id, agg.get('routing', ''),
                            row.get('stage', ''), row.get('levels', ''),
                            row.get('nodes', ''), row.get('netdevices', ''),
                            row.get('p2p_netdevices', ''), row.get('channels', ''),
                            row.get('ipv4', ''), row.get('ipv4_interfaces', ''),
                            row.get('routing_protocols', ''), row.get('rule_based_protocols', ''),
                            row.get('node_bfs_protocols', ''), row.get('rule_based_rules', ''),
                            row.get('routing_entries', ''), row.get('applications', ''),
                        ])
                    csvfile.flush()
                    mem_csvfile.flush()
                    obj_csvfile.flush()
                    to_remove.append(core_id)
                    idle_cores.append(core_id)
                    finished += 1

            for c in to_remove:
                running.pop(c, None)

            if idle_cores and pending:
                ok, s = mem_ok(mem_thresh_pct, mem_min_free_gb)
                if not ok:
                    print(f"[PAUSE] Memory guard active: used={s['used_pct']:.1f}%  avail={s['avail_gb']:.1f}GB "
                          f"(thr={mem_thresh_pct or '-'}% / min_free={mem_min_free_gb or '-'}GB). Retrying in {mem_poll_interval:.1f}s.")
                    time.sleep(mem_poll_interval)
                else:
                    for c in idle_cores:
                        if not pending:
                            break
                        try:
                            if not try_start_next_on(c):
                                time.sleep(0.5)
                        except Exception as e:
                            print(f"[ERROR] Unexpected error in main loop: {e}")
                            time.sleep(0.5)
            
            # try:
            #     s = mem_status()
            #     mem_line = f" mem_used={s['used_pct']:.1f}% avail={s['avail_gb']:.1f}GB"
            # except Exception:
            #     mem_line = ""
            # print(f"[STAT ] running={len(running):>2} pending={len(pending):>2} finished={finished:>2}/{total}{mem_line}",
            #       end='\r', flush=True)
            # time.sleep(0.2)

            stat_tuple = (len(running), len(pending), finished)
            if stat_tuple != last_stat:
                try:
                    s = mem_status()
                    mem_line = f" mem_used={s['used_pct']:.1f}% avail={s['avail_gb']:.1f}GB"
                except Exception:
                    mem_line = ""
                print(f"[STAT ] running={stat_tuple[0]:>2} pending={stat_tuple[1]:>2} "
                    f"finished={stat_tuple[2]:>2}/{total}{mem_line}")
                last_stat = stat_tuple
            time.sleep(5)

    print(f'\n[SUMMARY] {summary_csv}')
    print(f'[MEMPROF] {memory_profile_csv}')
    print(f'[OBJPROF] {object_profile_csv}')
    return summary_csv

def main():
    p = argparse.ArgumentParser(description='NSDI Orchestrator (auto-detect build tool + NUMA aware)')
    sub = p.add_subparsers(dest='action', required=True)

    ps = sub.add_parser('init', help='Install prerequisites and tune system (optional)')
    ps.add_argument('--disable-smt', action='store_true')
    ps.add_argument('--install', action='store_true')

    po = sub.add_parser('run-one', help='Run a single experiment on a specified core')
    po.add_argument('--name', required=True)
    po.add_argument('--taskset', required=True)
    po.add_argument('--config')
    po.add_argument('--topo')
    po.add_argument('--routing')
    po.add_argument('--data-size', type=int, dest='dataSize')
    po.add_argument('--degree', type=int)
    po.add_argument('--memory', action='store_true')
    po.add_argument('--perf', action='store_true')

    pr = sub.add_parser('run-set', help='Run a predefined set in parallel (auto configure+build)')
    pr.add_argument('--set', required=True, dest='setname')
    pr.add_argument('--cores', default=None)
    pr.add_argument('--max-par', type=int, default=None)
    pr.add_argument('--perf', action='store_true')
    pr.add_argument('--summary-prefix', default=None)
    pr.add_argument('--mem-thresh-pct', type=float, default=None)
    pr.add_argument('--mem-min-free-gb', type=float, default=None)
    pr.add_argument('--mem-poll-interval', type=float, default=1.0)
    pr.add_argument('--skip-build', action='store_true')
    pr.add_argument('--build-profile-override', choices=['debug','optimized', 'release'], default='release')
    pr.add_argument('--enable-examples-override', choices=['auto','yes','no'], default='yes')
    pr.add_argument('--numa-aware', action='store_true', help='Bind CPU+memory to NUMA node (uses numactl)')

    args = p.parse_args()

    if args.action == 'init':
        if args.install:
            os.system('sudo apt update')
            os.system('sudo apt install -y build-essential cmake git ninja-build linux-tools-generic linux-perf \
                       openmpi-bin openmpi-common libopenmpi-dev nfs-common \
                       texlive-latex-recommended texlive-fonts-extra')
        if args.disable_smt:
            os.system('echo off | sudo tee /sys/devices/system/cpu/smt/control')
        os.system('sudo sysctl -w kernel.perf_event_paranoid=-1')
        print('[INIT ] Done.')
        return

    if args.action == 'run-one':
        exp = Experiment(
            name=args.name,
            args=ExpArgs(config=args.config, topo=args.topo, routing=args.routing, dataSize=args.dataSize,
                         degree=args.degree, memory=args.memory),
            use_perf=args.perf
        )
        core = int(args.taskset)
        rc, agg, perf_file = run_one(exp, core)
        # parse perf + miss rate (single run)
        if perf_file and Path(perf_file).exists():
            agg.update(parse_perf_file(perf_file))
            cache_miss_rate(agg)
        print(f'[RC   ] {rc}'); print(f'[METR ] {agg}')
        if perf_file: print(f'[PERF ] {perf_file}')
        return

    if args.action == 'run-set':
        sets = build_experiment_sets()
        if args.setname not in sets:
            print('Available sets:', ', '.join(sorted(sets)))
            raise SystemExit(f'Unknown set: {args.setname}')
        spec = sets[args.setname]
        build_profile = args.build_profile_override or spec.build_profile
        if args.enable_examples_override == 'yes':
            enable_examples = True
        elif args.enable_examples_override == 'no':
            enable_examples = False
        else:
            enable_examples = spec.enable_examples
        if not args.skip_build:
            ns_configure_and_build(spec.name, build_profile, enable_examples)
        experiments = spec.experiments
        if args.perf:
            for e in experiments:
                e.use_perf = True
        cores = parse_cores(args.cores)
        if not cores:
            raise SystemExit('No cores parsed.')
        prefix = args.summary_prefix or f'{spec.name}-summary'
        orchestrate(experiments, cores, args.max_par, prefix,
                    mem_thresh_pct=args.mem_thresh_pct,
                    mem_min_free_gb=args.mem_min_free_gb,
                    mem_poll_interval=args.mem_poll_interval,
                    numa_aware=args.numa_aware)
        return

if __name__ == '__main__':
    main()
