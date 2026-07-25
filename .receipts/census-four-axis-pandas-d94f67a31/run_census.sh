#!/bin/bash
# Four-axis pandas census + per-function timing probe, both inside ONE BX lease.
#
# RUN 2. Run 1 (21:50:03Z) is VOID: the agent worktree it read the instrument
# from was deleted underneath the sweep at file ~125/1421, and lazily-imported
# sugar modules began raising ModuleNotFoundError. This run reads from a
# DURABLE worktree pinned at the same commit, outside .claude/worktrees/.
set -uo pipefail
W=/Users/tsavo/census-pin-d94f67a31
S=/private/tmp/claude-501/-Users-tsavo/d335638d-e107-473a-809c-b2e3e6d6f14e/scratchpad
PP=""
for d in "$W"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
export PANDAS_ROOT=$(python3 -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')
export W S
: > "$S/run-meta.txt"
{
  echo "RUN=2"
  echo "TREE=$W"
  echo "PANDAS_ROOT=$PANDAS_ROOT"
  echo "COMMIT=$(git -C "$W" rev-parse HEAD)"
  echo "UPTIME_BEFORE=$(uptime)"
  date -u +"LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
} >> "$S/run-meta.txt"
python3 "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census \
  --record "$S/lease-record.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$S/measurement-status" \
  --timeout 14400 \
  -- bash "$S/measured.sh"
rc=$?
{
  echo "LEASE_WRAPPER_EXIT=$rc"
  date -u +"END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER=$(uptime)"
  echo "FINAL_STATUS=$(cat "$S/measurement-status" 2>/dev/null)"
} >> "$S/run-meta.txt"
cat "$S/run-meta.txt"
