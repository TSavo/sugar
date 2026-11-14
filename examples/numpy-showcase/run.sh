#!/usr/bin/env bash
# The numpy showcase showdown: all the verbs over one operation, numpy.rot90.
#
#   mint        — two lift surfaces conjoin into one .proof: contract
#                 (numpy.testing, the PROPOSITION) + witness (pytest-witness, the
#                 EVIDENCE). numpy has no proof to import, so its calls stay
#                 unbound edges (not bridged).
#   prove       — the GOOD test discharges two ways (numpy.testing z3 CONSISTENT
#                 AND pytest-witness WITNESSED); the degenerate test (the same
#                 rot90 element asserted == 2 AND == 9) is REFUSED both ways
#                 (z3 UNSAT AND the witness run 'failed').
#
# Everything is kit-side; the .proof is the transport; rust stays proof-blind.
# NOTE: no `set -e`. `prove` exits nonzero on the (expected) degenerate refusal,
# exactly like pandas-showcase; this script captures the report and PASSES iff
# sugar produces the right verdict (good proved both ways, degenerate refused).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"

# The pytest-witness lifter RUNS numpy's test, and the numpy.testing lifter
# introspects numpy.testing to classify the assertion vocabulary -- both need
# numpy in a venv (PEP 668: never --break-system-packages). The lift manifests
# point their interpreter at this venv.
VENV="${NUMPY_WITNESS_VENV:-/tmp/numpy-witness-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
# The venv is a durable artifact that can persist, stale or partially built,
# across runs at a fixed /tmp path (a previous run's pip install may have
# failed quietly, or a required package may have been added since the venv
# was created). Never trust bin/python's mere existence: verify every
# required import actually resolves, and rebuild the deps if not. This is
# what keeps the durable row from silently going missing downstream.
if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import nacl
import numpy
import pytest
import sugar_lift_py_tests
import sugar_lift_python_source
import sugar_pytest_witness
PY
then
  "$VENV/bin/pip" install -q numpy pytest pynacl blake3 cbor2 \
    -e "$REPO/implementations/python/sugar-lift-py-tests" \
    -e "$REPO/implementations/python/sugar-lift-python-source" \
    -e "$REPO/implementations/python/sugar-lift-py-pytest-witness"
fi

cd "$HERE"
rm -f blake3-512_*.proof 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses 2>/dev/null || true
rm -f .sugar/imports/*.proof 2>/dev/null || true

echo "== mint both lifters -> one .proof =="
# contract (numpy.testing, the PROPOSITION) + witness (pytest-witness, the EVIDENCE).
"$BIN" mint --out . --library-bindings >/dev/null

echo "== prove (consistency AND witness) =="
report="$(PATH="$VENV/bin:$PATH" "$BIN" prove . 2>/dev/null)"
echo "$report"

echo ""
echo "== self-check: sugar must prove the good rot90 contract and refuse the degenerate both ways =="
fail=0
check_text() {
  local haystack="$1" label="$2" pattern="$3"
  # Avoid `echo "$report" | grep -q` under pipefail: grep can exit early
  # after a match, then echo may SIGPIPE and make a present verdict look absent.
  if grep -q "$pattern" <<<"$haystack"; then echo "  ok: $label"; else echo "  MISSING: $label ($pattern)"; fail=1; fi
}
check() { check_text "$report" "$1" "$2"; }
# Consistency axis: the good rot90 element facts discharge; the contradiction is UNSAT.
check "consistency discharges rot90 element facts"  "consistent about callsite .test_rot90_quarter_turn"
check "consistency REFUSES the contradiction"       "contradictory about callsite .test_rot90_contradiction"
# Witness axis: rust parses the package body; the good test passed in it, the degenerate failed.
check "witness REFUSES the degenerate from package body" "witness REFUSED by rust package body"
check "witness names the failing degenerate test"   "test_rot90_contradiction"

echo ""
echo "== verify durable artifact (expected refusal: the degenerate twin is in this proof) =="
verify_report="$(PATH="$VENV/bin:$PATH" "$BIN" prove . --json 2>&1)"
verify_rc=$?
echo "$verify_report"
if [ "$verify_rc" -eq 0 ]; then
  echo "  MISSING: durable verify must refuse the expected degenerate twin"
  fail=1
else
  echo "  ok: durable verify refused the expected degenerate twin (exit $verify_rc)"
fi
check_text "$verify_report" "durable verify preserves good rot90 discharge" "consistent about callsite .test_rot90_quarter_turn"
check_text "$verify_report" "durable verify preserves contradiction refusal" "contradictory about callsite .test_rot90_contradiction"
check_text "$verify_report" "durable verify recomputes witness package" '"verdict": "verified"'

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: numpy.rot90 proved correct (consistency AND witness); the degenerate refused both ways."
else
  echo "FAIL: sugar did not produce the expected verdict."; exit 1
fi
[ -z "${SHOWCASE_SUBJECT_WITNESS:-}" ] || printf '%s\n' "${SHOWCASE_SUBJECT_ID:?}" > "$SHOWCASE_SUBJECT_WITNESS"
