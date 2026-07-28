#!/bin/bash
# THE MEASURED SECTION. Refuses (non-zero) rather than let a killed or
# contaminated run be read as a zero. Same three refusals as the a02ebbe3e
# census: no summary block, a vanished instrument tree, or a partial
# denominator each VOID the run.
set -uo pipefail
LOG="$D/census-raw.log"
ROWS="$D/rows-fix.jsonl"

date -u +"CENSUS_START_UTC=%Y-%m-%dT%H:%M:%SZ" >> "$D/run-meta.txt"
$VENV/bin/python "$D/four_axis_resume.py" "$PANDAS_ROOT" \
  --checkpoint "$ROWS" \
  --start 0 --end 1420 \
  --timeout 300 \
  --workers 8 \
  --commit fix-6324-timeout-floor >> "$LOG" 2>&1
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
