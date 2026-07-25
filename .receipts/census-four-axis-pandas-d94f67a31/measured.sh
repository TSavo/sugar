#!/bin/bash
# The measured section. Runs ONLY inside the BX lease.
#
# EXIT STATUS DISCIPLINE (fixed after run 1):
# Run 1's version ended in an unconditional `exit 0`, so a census that was
# KILLED at file 269/1421 wrote `completed/zero-findings` into the status file
# -- the one status that may support a zero claim. That is precisely the
# confusion the lease's status vocabulary exists to prevent, reproduced by my
# own wrapper. This version propagates real status and never returns 0 unless
# BOTH phases actually completed.
set -uo pipefail
date -u +"CENSUS_START_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"
python3 -m sugar_lift_py_tests.census "$PANDAS_ROOT" > "$S/census-raw.log" 2>&1
census_rc=$?
echo "CENSUS_EXIT=$census_rc" | tee -a "$S/run-meta.txt"
date -u +"CENSUS_END_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"
echo "UPTIME_MID=$(uptime)" | tee -a "$S/run-meta.txt"

# A census that did not print its summary block did not finish. Never let the
# timing probe or the lease receipt speak for a truncated denominator.
if ! grep -q "^=== census: " "$S/census-raw.log"; then
  echo "CENSUS_TRUNCATED=yes (no summary block) -- REFUSING to claim a census" \
    | tee -a "$S/run-meta.txt"
  exit 70
fi
# The deleted-tree contamination class. If the instrument's OWN modules went
# missing mid-sweep, every row after that point is an environment artifact.
if grep -q "No module named 'sugar" "$S/census-raw.log"; then
  echo "CENSUS_CONTAMINATED=yes (instrument module vanished mid-sweep)" \
    | tee -a "$S/run-meta.txt"
  exit 70
fi

python3 "$S/fn_timing.py" "$PANDAS_ROOT" "$S/fn-timing.json" > "$S/fn-timing.log" 2>&1
timing_rc=$?
echo "TIMING_EXIT=$timing_rc" | tee -a "$S/run-meta.txt"
date -u +"TIMING_END_UTC=%Y-%m-%dT%H:%M:%SZ" | tee -a "$S/run-meta.txt"

# census exit 1 == measured, found findings (legitimate). Only a truncated or
# contaminated run, or a failed timing probe, is a harness failure.
if [ "$timing_rc" -ne 0 ]; then exit "$timing_rc"; fi
exit "$census_rc"
