#!/usr/bin/env bash
# pandas showcase: the same two-axis correctness claim as numpy-showcase, one
# rung up the ladder. The next library after numpy is NOT a new package -- it is
# the SAME one lifter (sugar_lift_py_tests.assertion_lsp), which learns pandas's
# vocabulary from each test file's imports plus a dropped-in data file,
# .sugar/vocab-exceptions/pandas.testing.json. This example differs from
# numpy-showcase only by that exception file and pointing the witness venv at pandas.
#
#   mint   — three lift surfaces run over the project: the plain pytest CONSISTENCY
#            surface (scalar assertions), the one assertion lifter learning
#            pandas.testing (frame assertions, approximate-by-default REFUSED unless
#            check_exact pinned), and the pytest-witness surface (RUNS the tests
#            under real pandas).
#   prove  — discharges two ways:
#              CONSISTENT : z3 finds the good contracts mutually consistent and
#                           the contradictory one UNSAT.
#              WITNESSED  : the witness re-runs pytest; the good tests reproduce,
#                           the contradictory one's run is 'failed'.
#
# The project deliberately contains a buggy (self-contradictory) test,
# test_pandas_sum_bad.py, so the showcase proves the CORRECT pandas code AND
# catches the contradiction -- refused BOTH ways. This script PASSES iff
# sugar produces exactly that verdict.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$REPO/implementations/rust/target/debug/sugar"

# The witness lifter RUNS pandas's tests, so it needs pandas + the kit deps in a
# venv (PEP 668: never --break-system-packages). The lift manifests point their
# interpreter at this venv.
VENV="${PANDAS_WITNESS_VENV:-/tmp/pandas-witness-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q pandas pytest pynacl blake3 cbor2
fi

cd "$HERE"
rm -f blake3-512_*.proof 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses 2>/dev/null || true

echo "== mint (plain-pytest + pandas.testing + pytest-witness over the project) =="
"$BIN" mint --out . --quiet

echo "== prove (consistency AND witness) =="
report="$(PATH="$VENV/bin:$PATH" "$BIN" prove . 2>/dev/null)"
echo "$report"

echo ""
echo "== self-check: sugar must prove the good code and refuse the bug both ways =="
fail=0
check_text() {
  local haystack="$1" label="$2" pattern="$3"
  # Avoid `echo "$report" | grep -q` under pipefail: grep can exit early
  # after a match, then echo may SIGPIPE and make a present verdict look absent.
  if grep -q "$pattern" <<<"$haystack"; then echo "  ok: $label"; else echo "  MISSING: $label ($pattern)"; fail=1; fi
}
check() { check_text "$report" "$1" "$2"; }
# Consistency axis: the two good contracts discharge, the contradiction is UNSAT.
check "consistency discharges Series.sum == 6"      "consistent about callsite .test_column_sum_is_six"
check "consistency discharges frame round-trip"     "consistent about callsite .test_frame_round_trips_exactly"
check "consistency REFUSES the contradiction"       "contradictory about callsite .test_column_sum_contradiction"
# Witness axis: ONE WitnessPackageMemento over the suite. Rust parses the
# package body: the good tests passed IN it, the contradictory test failed, so
# the package is refused, naming the failing test. The per-test facts live in
# the package.
check "witness package refused from package body"   "witness REFUSED by rust package body"
check "witness package names the failing test"      "test_column_sum_contradiction"
# read the per-test outcomes straight from the content-addressed package
"$VENV/bin/python" - <<'PY' || fail=1
import json, glob, sys
b = glob.glob(".sugar/witnesses/*.witness")
if not b: print("  MISSING: witness package"); sys.exit(1)
out = {}
for line in open(b[0], "rb"):
    line = line.strip()
    if line:
        w = json.loads(line); out[w["test"].split("::")[-1]] = w["outcome"]
ok  = out.get("test_column_sum_is_six") == "passed" and out.get("test_frame_round_trips_exactly") == "passed"
bad = out.get("test_column_sum_contradiction") == "failed"
print(f"  {'ok' if ok else 'MISSING'}: package records good tests passed")
print(f"  {'ok' if bad else 'MISSING'}: package records the contradiction failed")
sys.exit(0 if (ok and bad) else 1)
PY

echo ""
echo "== verify durable artifact (expected refusal: the contradictory twin is in this proof) =="
verify_report="$(PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json 2>&1)"
verify_rc=$?
echo "$verify_report"
if [ "$verify_rc" -eq 0 ]; then
  echo "  MISSING: durable verify must refuse the expected contradictory twin"
  fail=1
else
  echo "  ok: durable verify refused the expected contradictory twin (exit $verify_rc)"
fi
check_text "$verify_report" "durable verify preserves Series.sum discharge" "consistent about callsite .test_column_sum_is_six"
check_text "$verify_report" "durable verify preserves frame discharge" "consistent about callsite .test_frame_round_trips_exactly"
check_text "$verify_report" "durable verify preserves contradiction refusal" "contradictory about callsite .test_column_sum_contradiction"
check_text "$verify_report" "durable verify recomputes witness package" '"verdict": "verified"'

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: pandas proved correct (both axes); the contradictory test refused both ways."
else
  echo "FAIL: sugar did not produce the expected verdict."; exit 1
fi
