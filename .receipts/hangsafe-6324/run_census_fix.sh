#!/bin/bash
# Four-axis pandas census at the #6324 fix, on battleaxe, full 1421-file corpus.
#
# THE GATE THIS ANSWERS. #6319's 369-row desugarDefects drain must be PRESERVED,
# not assumed, and R(timeout) must be 0 over the whole corpus rather than over
# three files. Both are read off `rows-fix.jsonl` by the same `board.py` that
# produced `board-a4eade69a.json`, so the comparison is instrument-to-instrument.
#
# LEASE. Native run as user tsavo, so /var/tmp/sugar-heavy-measurement.lease is
# the one host-wide file every native measurement here contends on -- the same
# path the a02ebbe3e census took. The /home/runner/.cache/... default is the
# per-container path and does not exist on this host.
set -uo pipefail
W=$HOME/census-head-tree-6324
D=$HOME/census-6324
VENV=$HOME/census-a02-venv
mkdir -p "$D"
PP=""; for d in "$W"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
export W D VENV
PANDAS_ROOT=$($VENV/bin/python -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')
export PANDAS_ROOT

{
  echo "HOST=$(hostname)"
  echo "TREE=$W"
  echo "PANDAS_ROOT=$PANDAS_ROOT"
  echo "PANDAS_VERSION=$($VENV/bin/python -c 'import pandas;print(pandas.__version__)')"
  echo "COMMIT=$(cat $W/COMMIT.txt 2>/dev/null || echo unknown)"
  echo "NPROC=$(nproc)"
  echo "UPTIME_BEFORE=$(uptime)"
  date -u +"LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
} >> "$D/run-meta.txt"

$VENV/bin/python "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census-6324 \
  --record "$D/lease-record.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$D/measurement-status" \
  --timeout 28800 \
  -- bash "$D/measured.sh"
rc=$?
{
  echo "LEASE_WRAPPER_EXIT=$rc"
  date -u +"END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER=$(uptime)"
  echo "FINAL_STATUS=$(cat "$D/measurement-status" 2>/dev/null)"
} >> "$D/run-meta.txt"
exit $rc
