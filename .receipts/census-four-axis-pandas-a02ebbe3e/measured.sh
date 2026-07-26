#!/bin/bash
# THE MEASURED SECTION. Refuses (non-zero) rather than let a killed or
# contaminated run be read as a zero.
#
# Three refusal conditions, each a way a partial run has previously been banked
# as a complete one:
#   1. missing "=== SUMMARY ===" block  -> truncated / killed
#   2. "No module named 'sugar"         -> the instrument tree vanished
#   3. row conservation short of 1421   -> a partial denominator
set -uo pipefail
LOG="$D/census-raw.log"
ROWS="$D/rows.jsonl"

date -u +"CENSUS_START_UTC=%Y-%m-%dT%H:%M:%SZ" >> "$D/run-meta.txt"
python3 "$D/four_axis_resume.py" "$PANDAS_ROOT" \
  --checkpoint "$ROWS" \
  --start 0 --end 1420 \
  --timeout 300 \
  --workers 4 \
  --commit "$(git -C "$W" rev-parse HEAD)" >> "$LOG" 2>&1
census_rc=$?
{
  echo "CENSUS_EXIT=$census_rc"
  date -u +"CENSUS_END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER_CENSUS=$(uptime)"
} >> "$D/run-meta.txt"

fail=0
if grep -q "No module named 'sugar" "$LOG"; then
  echo "VOID: instrument tree vanished mid-run (No module named 'sugar...)" >&2
  fail=1
fi
if ! grep -q "=== SUMMARY ===" "$LOG"; then
  echo "VOID: no summary block -- run was truncated or killed" >&2
  fail=1
fi
rows=$(wc -l < "$ROWS" | tr -d ' ')
echo "ROWS_DURABLE=$rows" >> "$D/run-meta.txt"
if [ "$rows" -ne 1421 ]; then
  echo "INCOMPLETE: $rows/1421 durable rows -- resume before reporting any axis" >&2
  fail=1
fi
[ $census_rc -ne 0 ] && fail=1
exit $fail
