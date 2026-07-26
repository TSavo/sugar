#!/bin/bash
# Four-axis pandas census on battleaxe, commit-pinned at a02ebbe3e.
#
# WHY NOT THE MAC. The Mac was at load average 458 on 16 cores (fleet: rg, bfs,
# git, ~20 agents). Counter ratios survive that; a WALL-CLOCK THRESHOLD does
# not, and R(timeout) is exactly a wall-clock threshold. Measuring it at 30x
# oversubscription manufactures timeout rows that look like product red and
# that silently absorb every panic and defect row behind them -- the same
# failure that hid generic.py's rows at the old 300s deadline.
#
# The corpus is PROVEN identical, not assumed: pandas 3.0.3 in a pinned venv
# here yields 1421 files and corpusCid
# 22196d8904677ce92cdfbc0e0c0049ad7075ebc6ce56fc0336e3e6a51382cdd9 --
# byte-for-byte the Mac's. The instrument is proven portable on the same
# 6-file slice: identical fns/gaps/pairs/panics/defects on every file under
# python3.12 here and python3.14 there.
set -uo pipefail
W=$HOME/census-a02-tree
D="$W/.receipts/census-four-axis-pandas-a02ebbe3e"
VENV=$HOME/census-a02-venv
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
  echo "COMMIT=a02ebbe3ed37d6d7cdd6b3108ba1da09504ba0d4"
  echo "PYTHON=$($VENV/bin/python -VV | tr '\n' ' ')"
  echo "NPROC=$(nproc)"
  echo "UPTIME_BEFORE=$(uptime)"
  date -u +"LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
} >> "$D/run-meta-bx.txt"

$VENV/bin/python "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census-bx \
  --record "$D/lease-record-bx.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$D/measurement-status-bx" \
  --timeout 21600 \
  -- bash "$D/measured_bx.sh"
rc=$?
{
  echo "LEASE_WRAPPER_EXIT=$rc"
  date -u +"END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER=$(uptime)"
  echo "FINAL_STATUS=$(cat "$D/measurement-status-bx" 2>/dev/null)"
} >> "$D/run-meta-bx.txt"
exit $rc
