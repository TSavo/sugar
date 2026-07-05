#!/usr/bin/env bash
# python-urlsafe-seam: the CPython base64 standard-vs-urlsafe marquee.
#
# The URL-safe confusion refuted on an input the vendor never tested,
# statically, from the vendor's own source. CPython's b64encode delegates
# to C (binascii) -- honestly unwalkable -- but the SEAM is two byte
# literals of pure Python in Lib/base64.py:
#
#     _urlsafe_encode_translation = bytes.maketrans(b'+/', b'-_')
#     def urlsafe_b64encode(s): return b64encode(s).translate(...)
#
# translate is total, so urlsafe output NEVER contains '+' or '/'. The
# lifter walks that table (value-pinned, stability-scanned, swap-gated),
# gates it against the vendor's own test vectors (test.test_base64), and
# emits str.chars-not-in-set(subject, "+/") under the callsite's #euf#
# base. The bad twin asserts the standard-alphabet value ('+' at position
# 12) for the urlsafe encoder: equality row /\ universe row -> UNSAT.
#
# GOOD twin: correct urlsafe value -> consistency discharged.
# BAD twin:  the confusion        -> consistency refused (unsat).
#
# Input "provekit~seam" is absent from test.test_base64 (checked below):
# no point row could catch this; only the universe convicts.
#
# Verdicts are PARSED from real .verify.json consistency rows. Exit codes
# are never trusted; a missing row is a FAIL (vacuity guard: the conjuncts
# must MEET, absence of failure is not success).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TARGET_DIR="${CARGO_TARGET_DIR:-$REPO/implementations/rust/target}"
BIN="$("$REPO/bin/sugarbin" --profile release)"
VENV="${PYTHON_URLSAFE_SEAM_VENV:-/tmp/python-urlsafe-seam-venv}"
PYTHON="$VENV/bin/python"

[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }

if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$VENV"
fi
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import nacl
PY
then
  python3 -m venv --clear "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl
fi

echo "== provenance: the vendor never tested this input =="
provenance_rc=0
"$PYTHON" - <<'PY' || provenance_rc=$?
import importlib.util, sys
spec = importlib.util.find_spec("test.test_base64")
if spec is None or not spec.origin:
    print("SKIP: CPython test corpus not importable; provenance check unavailable")
    sys.exit(42)
src = open(spec.origin, encoding="utf-8", errors="replace").read()
if "provekit~seam" in src:
    print("FAIL: vendor now tests this input; pick a new seam input"); sys.exit(1)
print(f"OK: 'provekit~seam' absent from {spec.origin}")
PY
if [ "$provenance_rc" -eq 42 ]; then
  exit 0
fi
if [ "$provenance_rc" -ne 0 ]; then
  exit "$provenance_rc"
fi

run_twin() {
  local twin="$1" expect="$2"
  local dir="$HERE/$twin"
  echo
  echo "==================== twin: $twin (expect: $expect) ===================="
  rm -f "$dir"/blake3-512_*.proof 2>/dev/null
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/__pycache__" 2>/dev/null
  rm -f "$dir"/.prove*.json "$dir"/.verify*.json 2>/dev/null

  ( cd "$dir" && PATH="$VENV/bin:$PATH" "$BIN" mint --out . ) >/dev/null || { echo "FAIL: mint ($twin)"; return 1; }
  ( cd "$dir" && "$BIN" verify --project . --json > .verify.json ) || true
  [ -s "$dir/.verify.json" ] || { echo "FAIL: no verify receipt ($twin)"; return 1; }

  EXPECT="$expect" TWIN="$twin" "$PYTHON" - "$REPO" "$dir/.verify.json" <<'PY' || return 1
import os
import sys

sys.path.insert(0, sys.argv[1])
from tools.showcase.json_get import load_receipt

expect, twin = os.environ["EXPECT"], os.environ["TWIN"]
doc = load_receipt(sys.argv[2])
# The universe atom is a CONJUNCT inside the ::assertion inv (the verifier
# conjoins by name), so it does not appear as a separate property. The
# CONTACT/vacuity witness is the verdict FLIP itself: a universe that never
# met the equality would let BOTH twins discharge -- the bad twin refusing
# is the proof the conjuncts touched.
found = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "urlsafe_b64encode" in str(r.get("property", ""))
]
if not found:
    print(f"FAIL({twin}): no urlsafe_b64encode property rows in receipt"); sys.exit(1)
statuses = {s for _, s in found}
print(f"rows({twin}):")
for n, s in found:
    print(f"  {s:14s} {n[:110]}")
ok_words = {"discharged", "proven", "consistent", "sat"}
bad_words = {"unsatisfied", "refused", "unsat", "contradictory", "inconsistent", "violation", "violated"}
if expect == "discharged":
    verdict_ok = statuses & ok_words and not (statuses & bad_words)
else:
    verdict_ok = bool(statuses & bad_words)
if not verdict_ok:
    print(f"FAIL({twin}): expected {expect}, statuses={sorted(statuses)}"); sys.exit(1)
print(f"OK({twin}): {expect}")
PY
}

fail=0
run_twin good discharged || fail=1
run_twin bad refused || fail=1

echo
if [ "$fail" -ne 0 ]; then
  echo "==== python-urlsafe-seam: FAIL ===="
  exit 1
fi
echo "==== python-urlsafe-seam: PASS ===="
echo "the bad twin asserted the URL-safe confusion on an input the vendor"
echo "never tested -- refuted statically by two byte literals from the"
echo "vendor's own source. The call came from inside the house."
