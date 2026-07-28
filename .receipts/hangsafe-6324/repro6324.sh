#!/bin/bash
# #6324 bounded reproducer: the three files that crossed the 300s deadline at
# a4eade69a but completed in seconds at a02ebbe3e. Desugar-inclusive, per-file
# SIGALRM, counters ON -- wall time alone cannot separate "more work" from
# "same work, slower", and arm population must be readable apart from
# normalization work.
#
# LEASE. This runs natively on the battleaxe host as user tsavo, not in a
# container, so /var/tmp/sugar-heavy-measurement.lease IS the one host-wide
# file every native measurement here contends on -- the same path the
# a02ebbe3e census took its lease at. The per-container
# /home/runner/.cache/... default does not exist on this host.
set -uo pipefail
TREE=$1          # instrument tree (commit-pinned)
LABEL=$2
OUT=$3
DEADLINE=${4:-300}
VENV=$HOME/census-a02-venv
R=$HOME/repro-6324
PP=""; for d in "$TREE"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
PANDAS_ROOT=$($VENV/bin/python -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')

FILES=core/arrays/arrow/array.py,core/reshape/pivot.py,tests/extension/test_arrow.py

{
  echo "HOST=$(hostname) LABEL=$LABEL TREE=$TREE"
  echo "PANDAS=$($VENV/bin/python -c 'import pandas;print(pandas.__version__)') ROOT=$PANDAS_ROOT"
  echo "UPTIME_BEFORE=$(uptime)"
} >&2

$VENV/bin/python "$TREE/tools/heavy_measurement_lease.py" \
  --class hangsafe-6324 \
  --record "$R/lease-$LABEL.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$R/status-$LABEL" \
  --timeout 7200 \
  -- $VENV/bin/python "$R/desugar_repro.py" \
       --root "$PANDAS_ROOT" \
       --only "$FILES" \
       --deadline "$DEADLINE" \
       --counters \
       --no-stop-on-first-hang \
       --label "$LABEL" \
       --out "$OUT"
rc=$?
echo "EXIT=$rc UPTIME_AFTER=$(uptime)" >&2
exit $rc
