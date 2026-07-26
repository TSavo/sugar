#!/bin/bash
# Four-axis pandas census, commit-pinned at a02ebbe3e, per-file isolated and
# resumable, inside ONE machine-wide BX lease.
#
# The tree is DURABLE and outside .claude/worktrees/: the harness reaps those
# mid-run, and a prior census lost a full run that way -- silently converting
# the deletion into 9 fake ModuleNotFoundError CRASH rows that would have been
# reported as product red. The wrapper below refuses on that signature.
set -uo pipefail
W=/Users/tsavo/census-a02ebbe3e
D="$W/.receipts/census-four-axis-pandas-a02ebbe3e"
PP=""; for d in "$W"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
export W D
PANDAS_ROOT=$(python3 -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')
export PANDAS_ROOT

{
  echo "TREE=$W"
  echo "PANDAS_ROOT=$PANDAS_ROOT"
  echo "COMMIT=$(git -C "$W" rev-parse HEAD)"
  echo "PYTHON=$(python3 -VV | tr '\n' ' ')"
  echo "UPTIME_BEFORE=$(uptime)"
  date -u +"LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
} >> "$D/run-meta.txt"

python3 "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census \
  --record "$D/lease-record.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$D/measurement-status" \
  --timeout 21600 \
  -- bash "$D/measured.sh"
rc=$?
{
  echo "LEASE_WRAPPER_EXIT=$rc"
  date -u +"END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER=$(uptime)"
  echo "FINAL_STATUS=$(cat "$D/measurement-status" 2>/dev/null)"
} >> "$D/run-meta.txt"
exit $rc
