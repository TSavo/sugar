#!/bin/bash
# BOUNDED REPLAY at current head c11767c5e, over candidate sites only.
# Reads the HEAD worktree; compares against the PINNED dump.
set -uo pipefail
H=/Users/tsavo/census-head-c11767c5e
S=/private/tmp/claude-501/-Users-tsavo/d335638d-e107-473a-809c-b2e3e6d6f14e/scratchpad
PP=""
for d in "$H"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
export H S
{
  echo "REPLAY_COMMIT=$(git -C "$H" rev-parse HEAD)"
  date -u +"REPLAY_LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "REPLAY_UPTIME_BEFORE=$(uptime)"
} >> "$S/run-meta.txt"
python3 "$H/tools/heavy_measurement_lease.py" \
  --class pandas-bounded-replay-c11767c5e \
  --record "$S/lease-record-replay.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$S/measurement-status-replay" \
  --timeout 14400 \
  -- python3 "$S/bounded_replay.py" "$S/full-dump.json" "$S/bounded-replay.json" NameErrorEffect
rc=$?
{
  echo "REPLAY_EXIT=$rc"
  date -u +"REPLAY_END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "REPLAY_UPTIME_AFTER=$(uptime)"
} >> "$S/run-meta.txt"
