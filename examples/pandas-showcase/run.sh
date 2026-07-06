#!/usr/bin/env bash
# pandas showcase: the same two-axis correctness claim as numpy-showcase, one
# rung up the ladder. The Python factory lift RPC handles both the plain pytest
# surface and the pandas.testing surface; pandas-specific helper exceptions live
# in .sugar/vocab-exceptions/pandas.testing.json. This example differs from
# numpy-showcase only by that exception file and pointing the witness venv at pandas.
#
#   mint   — three lift surfaces run over the project: the plain pytest CONSISTENCY
#            surface (scalar assertions), the one assertion lifter learning
#            pandas.testing (frame assertions, approximate-by-default typed red unless
#            check_exact pinned), and the pytest-witness surface (RUNS the tests
#            under real pandas).
#   prove  — discharges two ways:
#              CONSISTENT : z3 finds the good contracts mutually consistent and
#                           the contradictory one UNSAT.
#              WITNESSED  : the witness re-runs pytest; the good tests reproduce,
#                           the contradictory one's run is 'failed'.
#
# The project deliberately contains a buggy (self-contradictory) test,
# test_pandas_sum_bad.py, so the showcase proves the CORRECT pandas code by
# witness replay and catches the contradiction by structural consistency. This
# script PASSES iff sugar produces exactly that verdict.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"

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
rm -f .verify.raw .verify.json 2>/dev/null || true

echo "== mint (plain-pytest + pandas.testing + pytest-witness over the project) =="
"$BIN" mint --out . --quiet

echo "== prove (consistency AND witness) =="
report="$(PATH="$VENV/bin:$PATH" "$BIN" prove --allow-failed-components . 2>/dev/null)"
echo "$report"

echo ""
echo "== self-check: sugar must replay the good tests and catch the bad twin =="
fail=0
check_text() {
  local haystack="$1" label="$2" pattern="$3"
  # Avoid `echo "$report" | grep -q` under pipefail: grep can exit early
  # after a match, then echo may SIGPIPE and make a present verdict look absent.
  if grep -q "$pattern" <<<"$haystack"; then echo "  ok: $label"; else echo "  MISSING: $label ($pattern)"; fail=1; fi
}
check() { check_text "$report" "$1" "$2"; }
# Consistency axis: the bad twin says the same structural call is both 6 and 7.
check "consistency catches the Series.sum contradiction" "test assertions contradictory about callsite \`sum#euf#c:call:sum()::assertion\`"
check "consistency names both bad-twin values"           "equals both"
check "witness package provenance red remains loud"      "lacks required provenance KIND"
# Witness axis: ONE WitnessPackageMemento over the suite. The per-test facts live
# in the package: the good tests passed, the deliberately contradictory test
# failed, so the bad twin cannot masquerade as a green example.
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
verify_report="$(PATH="$VENV/bin:$PATH" "$BIN" verify --allow-failed-components --project . --json 2>&1)"
verify_rc=$?
echo "$verify_report"
printf '%s\n' "$verify_report" > .verify.raw
"$VENV/bin/python" - <<'PY' || fail=1
import json
import sys
from pathlib import Path

text = Path(".verify.raw").read_text(encoding="utf-8")
decoder = json.JSONDecoder()
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, _ = decoder.raw_decode(text[i:])
    except json.JSONDecodeError:
        continue
    Path(".verify.json").write_text(
        json.dumps(obj, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sys.exit(0)
print("  MISSING: durable verify JSON receipt")
sys.exit(1)
PY
if [ "$verify_rc" -eq 0 ]; then
  echo "  MISSING: durable verify must refuse the expected contradictory twin"
  fail=1
else
  echo "  ok: durable verify refused the expected contradictory twin (exit $verify_rc)"
fi
"$VENV/bin/python" - "$REPO" <<'PY' || fail=1
import sys

sys.path.insert(0, sys.argv[1])
from tools.showcase.json_get import load_receipt

receipt = load_receipt(".verify.json")
rows = receipt.get("rows", [])

def matching_rows(needle):
    return [r for r in rows if needle in (r.get("property") or "")]

def require(label, condition):
    print(f"  {'ok' if condition else 'MISSING'}: {label}")
    return bool(condition)

ok = True
bad_rows = matching_rows("sum#euf#c:call:sum()::assertion")
bad_reason = " ".join(str(r.get("reason") or "") for r in bad_rows)
ok = require(
    "durable verify preserves the Series.sum contradiction",
    len(bad_rows) == 1
    and bad_rows[0].get("status") == "unsatisfied"
    and "equals both" in bad_reason
    and '"value":6' in bad_reason
    and '"value":7' in bad_reason,
) and ok

witness_rows = matching_rows("witness-package")
witness_reason = " ".join(str(r.get("reason") or "") for r in witness_rows)
ok = require(
    "durable verify preserves the witness provenance red",
    len(witness_rows) == 1
    and witness_rows[0].get("status") == "refused"
    and "lacks required provenance KIND" in witness_reason,
) and ok

witnesses = receipt.get("witnessDimension", {}).get("witnesses", [])
ok = require(
    "durable verify recomputes the witness package",
    any(w.get("verdict") == "verified" for w in witnesses),
) and ok
ok = require(
    "durable verify summary is discharged=0 violations=1 refused=1 ok=false",
    receipt.get("discharged") == 0
    and receipt.get("violations") == 1
    and receipt.get("refused") == 1
    and receipt.get("ok") is False,
) and ok
sys.exit(0 if ok else 1)
PY

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: pandas replayed the good tests; the contradictory test stayed red."
else
  echo "FAIL: sugar did not produce the expected verdict."; exit 1
fi
