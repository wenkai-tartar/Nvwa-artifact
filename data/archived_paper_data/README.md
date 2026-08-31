# Full Paper Data

This directory contains the archived CSV inputs for the final paper experiment
figures. From the repository root, use:

```bash
bash plots/plot_figures.sh --full-data all
```

to regenerate the full paper plots into `results/full_data_figures/`.

The wrapper writes normalized final-paper outputs such as
`results/full_data_figures/figure8a/figure8a.pdf`. `full_data_figure_outputs.csv`
records the mapping from archived inputs to normalized figure outputs.

Coverage:

- Figure 1(a)-(c): final-version initialization and memory profiling additions
- Figure 8: topology-scale memory
- Figure 9: topology-scale initialization time
- Figure 10: topology-scale execution time and Fat-tree total time
- Figure 11: workload-size execution time
- Figure 12: final-version ATLAHS Dragonfly production-workload addition
- Figure 13: Fat-tree failure handling
- Figure 14: non-minimal routing overhead

The original archived CSVs for Figure 8-Figure 11, Figure 13, and Figure 14 are
kept at the top level of this directory. Figure 1(a)-(c) and Figure 12 were
added after the original archive and are stored under `final_figure1/` and
`final_figure12/` so the archived path matches the final paper version seen by
AEC reviewers.
