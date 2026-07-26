#!/bin/bash
# THE MEASURED SECTION. Refuses rather than let a killed run read as a zero.
set -uo pipefail
LOG="$D/census-raw-head.log"; ROWS="$D/rows-head.jsonl"
date -u +"CENSUS_START_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$D/run-meta-head.txt"
$VENV/bin/python "$D/four_axis_resume.py" "$PANDAS_ROOT" \
  --checkpoint "$ROWS" --start 0 --end 1420 --timeout 300 --workers 8 \
  --commit a4eade69abb0b20d12a50d7ffbc9ec1134ed5f05 2>&1 | tee -a "$LOG"
census_rc=${PIPESTATUS[0]}
{ echo "CENSUS_EXIT=$census_rc"; date -u +"CENSUS_END_UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "UPTIME_AFTER_CENSUS=$(uptime)"; } | tee -a "$D/run-meta-head.txt"
fail=0
grep -q "No module named 'sugar" "$LOG" && { echo "VOID: instrument tree vanished mid-run" >&2; fail=1; }
grep -q "=== SUMMARY ===" "$LOG" || { echo "VOID: no summary block -- truncated or killed" >&2; fail=1; }
rows=$(wc -l < "$ROWS" | tr -d ' ')
echo "ROWS_DURABLE=$rows" | tee -a "$D/run-meta-head.txt"
[ "$rows" -ne 1421 ] && { echo "INCOMPLETE: $rows/1421 -- resume before reporting any axis" >&2; fail=1; }
[ $census_rc -ne 0 ] && fail=1
exit $fail
