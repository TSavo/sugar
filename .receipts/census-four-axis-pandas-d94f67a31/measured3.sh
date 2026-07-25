#!/bin/bash
set -uo pipefail
date -u +"DUMP_START_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"
python3 "$S/full_dump.py" "$PANDAS_ROOT" "$S/full-dump.json" > "$S/full-dump.log" 2>&1
dump_rc=$?
echo "DUMP_EXIT=$dump_rc" | tee -a "$S/run-meta.txt"
date -u +"DUMP_END_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"
if grep -q "No module named 'sugar" "$S/full-dump.log"; then
  echo "DUMP_CONTAMINATED=yes" | tee -a "$S/run-meta.txt"; exit 70
fi
if [ "$dump_rc" -ne 0 ]; then exit "$dump_rc"; fi

python3 "$S/rank_stability.py" "$S/fn-timing.json" "$S/rank-stability.json" 40 \
  > "$S/rank-stability.log" 2>&1
echo "RANK_EXIT=$?" | tee -a "$S/run-meta.txt"
date -u +"RANK_END_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"
exit 0
