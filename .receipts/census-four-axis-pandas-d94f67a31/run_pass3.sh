#!/bin/bash
# PASS 3, inside its own BX lease acquisition:
#   a) untruncated four-axis dump (census printed only 40 of 1074 panic rows)
#   b) rank-stability replay of the top-40 worst functions
# Both read the SAME durable pinned tree as run 2.
set -uo pipefail
W=/Users/tsavo/census-pin-d94f67a31
S=/private/tmp/claude-501/-Users-tsavo/d335638d-e107-473a-809c-b2e3e6d6f14e/scratchpad
PP=""
for d in "$W"/implementations/python/*/src; do PP="$PP:$d"; done
export PYTHONPATH="${PP#:}"
export PYTHONUNBUFFERED=1
export PANDAS_ROOT=$(python3 -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')
export W S
{
  echo "PASS3_COMMIT=$(git -C "$W" rev-parse HEAD)"
  date -u +"PASS3_LEASE_REQUEST_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "PASS3_UPTIME_BEFORE=$(uptime)"
} >> "$S/run-meta.txt"
python3 "$W/tools/heavy_measurement_lease.py" \
  --class pandas-four-axis-census-fulldump \
  --record "$S/lease-record-pass3.json" \
  --lease /var/tmp/sugar-heavy-measurement.lease \
  --status-file "$S/measurement-status-pass3" \
  --timeout 14400 \
  -- bash "$S/measured3.sh"
rc=$?
{
  echo "PASS3_EXIT=$rc"
  date -u +"PASS3_END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "PASS3_UPTIME_AFTER=$(uptime)"
} >> "$S/run-meta.txt"
tail -20 "$S/run-meta.txt"
