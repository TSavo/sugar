#!/bin/bash
# Four-axis pandas census at a4eade69a (#6319), on battleaxe, under the REAL
# machine-wide lease.
#
# LEASE PATH. `DEFAULT_LEASE_PATH` is /home/runner/.cache/sugar/binaries/... —
# correct INSIDE a runner container. This run is ssh-direct as tsavo, where
# /home/runner/.cache does not exist. `docker inspect` shows the containers'
# /home/runner/.cache/sugar/binaries is bind-mounted from the host directory
# /home/tsavo/.cache/sugar/binaries, so THAT is the same physical file the
# containers lock. Using it serializes against runner jobs; /var/tmp would not.
set -uo pipefail
W=$HOME/census-main-tree
D="$W/.receipts/census-four-axis-pandas-a02ebbe3e"
VENV=$HOME/census-a02-venv
LEASE=/home/tsavo/.cache/sugar/binaries/.sugar-heavy-measurement.lease
PP=""; for d in "$W"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}" PYTHONUNBUFFERED=1 W D VENV
PANDAS_ROOT=$($VENV/bin/python -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')
export PANDAS_ROOT
{
  echo "HOST=$(hostname)"; echo "TREE=$W"; echo "LEASE=$LEASE"
  echo "PANDAS_ROOT=$PANDAS_ROOT"
  echo "PANDAS_VERSION=$($VENV/bin/python -c 'import pandas;print(pandas.__version__)')"
  echo "COMMIT=a4eade69abb0b20d12a50d7ffbc9ec1134ed5f05"
  echo "PYTHON=$($VENV/bin/python -VV | tr '\n' ' ')"; echo "NPROC=$(nproc)"
  echo "UPTIME_BEFORE=$(uptime)"; date -u +"LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
} | tee -a "$D/run-meta-head.txt"
$VENV/bin/python "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census-head \
  --record "$D/lease-record-head.json" \
  --lease "$LEASE" \
  --status-file "$D/measurement-status-head" \
  --timeout 21600 \
  -- bash "$D/measured_head.sh" 2>&1 | tee -a "$D/lease-head.log"
rc=${PIPESTATUS[0]}
{ echo "LEASE_WRAPPER_EXIT=$rc"; date -u +"END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER=$(uptime)"
  echo "FINAL_STATUS=$(cat "$D/measurement-status-head" 2>/dev/null)"; } | tee -a "$D/run-meta-head.txt"
exit $rc
