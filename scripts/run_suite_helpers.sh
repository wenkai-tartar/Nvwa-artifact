#!/usr/bin/env bash

suite_timestamp() {
  date -u +%Y%m%dT%H%M%S%NZ
}

suite_normalize_experiment() {
  local value="${1,,}"
  value="${value#experiment}"
  value="${value#exp}"
  case "${value}" in
    1|2|3|4|5|6|7|8|9) printf '%s\n' "${value}" ;;
    *) return 1 ;;
  esac
}

suite_resolve_pointer() {
  local pointer="$1"
  [[ -f "${pointer}" ]] || return 1

  local target
  target="$(<"${pointer}")"
  [[ -n "${target}" ]] || return 1
  if [[ "${target}" != /* ]]; then
    target="$(cd "$(dirname "${pointer}")" && pwd)/${target}"
  fi
  [[ -d "${target}" ]] || return 1
  cd "${target}" && pwd
}

suite_result_pattern() {
  case "$1" in
    1) printf '%s\n' "experiment1_fattree_ring_allreduce_*" ;;
    2) printf '%s\n' "experiment4_fattree_memory_profile_*" ;;
    3) printf '%s\n' "experiment7_nodebfs_initialization_time_profile_*" ;;
    4) printf '%s\n' "experiment2_dragonfly_ring_allreduce_*" ;;
    5) printf '%s\n' "experiment3_torus_ring_allreduce_*" ;;
    6) printf '%s\n' "experiment6_atlahs_dragonfly_production_workload_*" ;;
    7) printf '%s\n' "experiment8_workload_size_allreduce_*" ;;
    8) printf '%s\n' "experiment9_fattree_failure_handling_*" ;;
    9) printf '%s\n' "experiment10_nonminimal_routing_*" ;;
    *) return 1 ;;
  esac
}

suite_current_pointer_name() {
  case "$1" in
    1) printf '%s\n' "current_experiment1_fattree_ring_allreduce.txt" ;;
    2) printf '%s\n' "current_experiment4_fattree_memory_profile.txt" ;;
    3) printf '%s\n' "current_experiment7_nodebfs_initialization_time_profile.txt" ;;
    4) printf '%s\n' "current_experiment2_dragonfly_ring_allreduce.txt" ;;
    5) printf '%s\n' "current_experiment3_torus_ring_allreduce.txt" ;;
    6) printf '%s\n' "current_experiment6_atlahs_dragonfly_production_workload.txt" ;;
    7) printf '%s\n' "current_experiment8_workload_size_allreduce.txt" ;;
    8) printf '%s\n' "current_experiment9_fattree_failure_handling.txt" ;;
    9) printf '%s\n' "current_experiment10_nonminimal_routing.txt" ;;
    *) return 1 ;;
  esac
}

suite_latest_result_dir() {
  local results_root="$1"
  local pattern="$2"
  find "${results_root}" -maxdepth 1 -type d -name "${pattern}" -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | sed -n '1s/^[^ ]* //p'
}

suite_file_nonempty() {
  [[ -s "$1" ]]
}

suite_data_dir() {
  local results_root="$1"
  printf '%s/data\n' "${results_root}"
}

suite_csv_complete() {
  python3 - "$1" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file() or path.stat().st_size == 0:
    raise SystemExit(1)

with path.open(newline="", encoding="utf-8-sig") as handle:
    reader = csv.DictReader(handle)
    if not reader.fieldnames:
        raise SystemExit(1)
    has_rc = "rc" in reader.fieldnames
    rows = 0
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        rows += 1
        if has_rc and (row.get("rc") or "").strip() not in {"0", "0.0"}:
            raise SystemExit(1)
    if rows == 0:
        raise SystemExit(1)
PY
}

suite_copy_data_file() {
  local dest="$1"
  shift

  local src
  for src in "$@"; do
    if [[ -s "${src}" ]]; then
      mkdir -p "$(dirname "${dest}")"
      cp -f "${src}" "${dest}"
      return 0
    fi
  done

  echo "[error] missing source data for ${dest}" >&2
  return 1
}

suite_flat_outputs_complete() {
  local experiment="$1"
  local data_dir="$2"
  [[ -d "${data_dir}" ]] || return 1

  case "${experiment}" in
    1)
      suite_csv_complete "${data_dir}/experiment_1.csv"
      ;;
    2)
      suite_csv_complete "${data_dir}/experiment_2_summary.csv" &&
        suite_file_nonempty "${data_dir}/experiment_2_memory_profile.csv" &&
        suite_file_nonempty "${data_dir}/experiment_2_object_profile.csv"
      ;;
    3)
      suite_csv_complete "${data_dir}/experiment_3_summary.csv" &&
        suite_file_nonempty "${data_dir}/experiment_3_time_profile.csv" &&
        suite_file_nonempty "${data_dir}/experiment_3_time_breakdown.csv"
      ;;
    4)
      suite_csv_complete "${data_dir}/experiment_4.csv"
      ;;
    5)
      suite_csv_complete "${data_dir}/experiment_5.csv"
      ;;
    6)
      suite_csv_complete "${data_dir}/experiment_6.csv" &&
        suite_file_nonempty "${data_dir}/experiment_6_manifest.json"
      ;;
    7)
      suite_csv_complete "${data_dir}/experiment_7_dragonfly.csv" &&
        suite_csv_complete "${data_dir}/experiment_7_fattree.csv"
      ;;
    8)
      suite_csv_complete "${data_dir}/experiment_8.csv"
      ;;
    9)
      suite_csv_complete "${data_dir}/experiment_9.csv"
      ;;
    *)
      return 1
      ;;
  esac
}

suite_publish_experiment_data() {
  local results_root="$1"
  local experiment="$2"
  local run_dir="$3"
  local data_dir
  data_dir="$(suite_data_dir "${results_root}")"
  mkdir -p "${data_dir}"

  case "${experiment}" in
    1)
      suite_copy_data_file "${data_dir}/experiment_1.csv" \
        "${run_dir}/experiment_1.csv"
      ;;
    2)
      suite_copy_data_file "${data_dir}/experiment_2_summary.csv" \
        "${run_dir}/experiment_2_summary.csv" \
        "${run_dir}/ns3_datacenter_nodebfs/experiment_2_summary.csv" &&
      suite_copy_data_file "${data_dir}/experiment_2_memory_profile.csv" \
        "${run_dir}/experiment_2_memory_profile.csv" \
        "${run_dir}/ns3_datacenter_nodebfs/experiment_2_memory_profile.csv" &&
      suite_copy_data_file "${data_dir}/experiment_2_object_profile.csv" \
        "${run_dir}/experiment_2_object_profile.csv" \
        "${run_dir}/ns3_datacenter_nodebfs/experiment_2_object_profile.csv"
      ;;
    3)
      suite_copy_data_file "${data_dir}/experiment_3_summary.csv" \
        "${run_dir}/experiment_3_summary.csv" &&
      suite_copy_data_file "${data_dir}/experiment_3_time_profile.csv" \
        "${run_dir}/experiment_3_time_profile.csv" &&
      suite_copy_data_file "${data_dir}/experiment_3_time_breakdown.csv" \
        "${run_dir}/experiment_3_time_breakdown.csv"
      ;;
    4)
      suite_copy_data_file "${data_dir}/experiment_4.csv" \
        "${run_dir}/experiment_4.csv"
      ;;
    5)
      suite_copy_data_file "${data_dir}/experiment_5.csv" \
        "${run_dir}/experiment_5.csv"
      ;;
    6)
      suite_copy_data_file "${data_dir}/experiment_6.csv" \
        "${run_dir}/experiment_6.csv" &&
      suite_copy_data_file "${data_dir}/experiment_6_manifest.json" \
        "${run_dir}/experiment_6_manifest.json" \
        "${run_dir}/manifest.json"
      ;;
    7)
      suite_copy_data_file "${data_dir}/experiment_7_dragonfly.csv" \
        "${run_dir}/experiment_7_dragonfly.csv" \
        "${run_dir}/dragonfly/experiment_7_dragonfly.csv" &&
      suite_copy_data_file "${data_dir}/experiment_7_fattree.csv" \
        "${run_dir}/experiment_7_fattree.csv" \
        "${run_dir}/fattree/experiment_7_fattree.csv"
      ;;
    8)
      suite_copy_data_file "${data_dir}/experiment_8.csv" \
        "${run_dir}/experiment_8.csv"
      ;;
    9)
      suite_copy_data_file "${data_dir}/experiment_9.csv" \
        "${run_dir}/experiment_9.csv"
      ;;
    *)
      return 1
      ;;
  esac

  suite_flat_outputs_complete "${experiment}" "${data_dir}" || return 1
  printf '%s\n' "${data_dir}"
}

suite_experiment_outputs_complete() {
  local experiment="$1"
  local run_dir="$2"
  [[ -d "${run_dir}" ]] || return 1

  case "${experiment}" in
    1)
      suite_csv_complete "${run_dir}/experiment_1.csv"
      ;;
    2)
      suite_csv_complete "${run_dir}/ns3_datacenter_nodebfs/experiment_2_summary.csv" &&
        suite_file_nonempty "${run_dir}/ns3_datacenter_nodebfs/experiment_2_memory_profile.csv" &&
        suite_file_nonempty "${run_dir}/ns3_datacenter_nodebfs/experiment_2_object_profile.csv"
      ;;
    3)
      suite_csv_complete "${run_dir}/experiment_3_summary.csv" &&
        suite_file_nonempty "${run_dir}/experiment_3_time_profile.csv" &&
        suite_file_nonempty "${run_dir}/experiment_3_time_breakdown.csv"
      ;;
    4)
      suite_csv_complete "${run_dir}/experiment_4.csv"
      ;;
    5)
      suite_csv_complete "${run_dir}/experiment_5.csv"
      ;;
    6)
      suite_csv_complete "${run_dir}/experiment_6.csv" &&
        suite_file_nonempty "${run_dir}/manifest.json"
      ;;
    7)
      suite_csv_complete "${run_dir}/dragonfly/experiment_7_dragonfly.csv" &&
        suite_csv_complete "${run_dir}/fattree/experiment_7_fattree.csv"
      ;;
    8)
      suite_csv_complete "${run_dir}/experiment_8.csv"
      ;;
    9)
      suite_csv_complete "${run_dir}/experiment_9.csv"
      ;;
    *)
      return 1
      ;;
  esac
}

suite_status_file() {
  local results_root="$1"
  local experiment="$2"
  printf '%s/experiment_status/experiment_%s.done\n' "${results_root}" "${experiment}"
}

suite_completed_run_dir() {
  local results_root="$1"
  local experiment="$2"
  local status_file
  status_file="$(suite_status_file "${results_root}" "${experiment}")"
  [[ -s "${status_file}" ]] || return 1

  local run_dir
  run_dir="$(<"${status_file}")"
  [[ -d "${run_dir}" ]] || return 1
  suite_experiment_outputs_complete "${experiment}" "${run_dir}" || return 1
  printf '%s\n' "${run_dir}"
}

suite_current_run_dir() {
  local results_root="$1"
  local experiment="$2"
  local pointer_name
  pointer_name="$(suite_current_pointer_name "${experiment}")" || return 1
  suite_resolve_pointer "${results_root}/${pointer_name}"
}

suite_any_run_dir() {
  local results_root="$1"
  local experiment="$2"
  if suite_current_run_dir "${results_root}" "${experiment}"; then
    return 0
  fi

  local pattern
  pattern="$(suite_result_pattern "${experiment}")" || return 1
  suite_latest_result_dir "${results_root}" "${pattern}"
}

suite_mark_experiment_done() {
  local results_root="$1"
  local experiment="$2"
  local run_dir
  run_dir="$(suite_any_run_dir "${results_root}" "${experiment}")"
  [[ -n "${run_dir}" ]] || return 1
  suite_experiment_outputs_complete "${experiment}" "${run_dir}" || return 1
  suite_publish_experiment_data "${results_root}" "${experiment}" "${run_dir}" >/dev/null || return 1

  mkdir -p "${results_root}/experiment_status"
  printf '%s\n' "${run_dir}" > "$(suite_status_file "${results_root}" "${experiment}")"
  printf '%s\n' "${run_dir}"
}
