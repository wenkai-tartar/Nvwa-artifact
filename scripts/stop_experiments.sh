#!/usr/bin/env bash
set -euo pipefail

PATTERN='run_lightweight_experiments[.]sh|run_full_experiments[.]sh|run_experiment[0-9]+_|run_fattree|run_topology_ring_allreduce_stats[.]py|fattree_memory_profile_sweep[.]py|fattree_time_profile_sweep[.]py|fattree_failure_sweep[.]py|nonminimal_sweep[.]py|dragonfly_trace_sweep[.]py|atlahs_.*_to_nvwa_trace[.]py|compare_constructor_packet_traces[.]py|ns3 run constructor|constructor-optimized|constructor --config='
GRACE_SECONDS="${GRACE_SECONDS:-10}"

collect_pids() {
  pgrep -f "${PATTERN}" | sort -n | uniq | while read -r pid; do
    [[ -z "${pid}" ]] && continue
    [[ "${pid}" == "$$" ]] && continue
    [[ "${pid}" == "${PPID}" ]] && continue
    if [[ -r "/proc/${pid}/cmdline" ]]; then
      printf '%s\n' "${pid}"
    fi
  done
}

mapfile -t pids < <(collect_pids)

if [[ "${#pids[@]}" -eq 0 ]]; then
  echo "No matching AE experiment processes found."
  exit 0
fi

echo "Stopping AE experiment processes:"
for pid in "${pids[@]}"; do
  ps -o pid,ppid,pgid,etime,%cpu,%mem,rss,cmd -p "${pid}" --no-headers || true
done

kill -TERM "${pids[@]}" 2>/dev/null || true
sleep "${GRACE_SECONDS}"

mapfile -t remaining < <(collect_pids)
if [[ "${#remaining[@]}" -gt 0 ]]; then
  echo "Force-stopping remaining AE experiment processes:"
  for pid in "${remaining[@]}"; do
    ps -o pid,ppid,pgid,etime,%cpu,%mem,rss,cmd -p "${pid}" --no-headers || true
  done
  kill -KILL "${remaining[@]}" 2>/dev/null || true
fi

sleep 1
mapfile -t final_remaining < <(collect_pids)
if [[ "${#final_remaining[@]}" -gt 0 ]]; then
  echo "Some matching processes are still present:"
  for pid in "${final_remaining[@]}"; do
    ps -o pid,ppid,pgid,etime,%cpu,%mem,rss,cmd -p "${pid}" --no-headers || true
  done
  exit 1
fi

echo "All matching AE experiment processes stopped."
