#!/usr/bin/env bash
# sklearn showcase: real scikit-learn vendor rows lifted as scalar consistency
# contracts and witnessed by re-running pytest under real scikit-learn.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"

# The witness lifter RUNS sklearn tests, so it needs scikit-learn + the kit deps
# in a venv (PEP 668: never --break-system-packages). The lift manifests point
# their interpreter at this venv.
VENV="${SKLEARN_WITNESS_VENV:-/tmp/sklearn-witness-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import nacl
import pytest
import sklearn
PY
then
  "$VENV/bin/pip" install -q 'scikit-learn==1.9.0' pytest pynacl blake3 cbor2
fi

cd "$HERE"
rm -f blake3-512_*.proof 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses 2>/dev/null || true
rm -f .verify.raw .verify.json 2>/dev/null || true

echo "== mint (plain-pytest + sklearn.utils._testing + pytest-witness over the project) =="
"$BIN" mint --out . --quiet

echo "== prove (consistency AND witness) =="
report="$(PATH="$VENV/bin:$PATH" "$BIN" prove --allow-failed-components . 2>/dev/null)"
echo "$report"

echo ""
echo "== self-check: sugar must keep the good rows loud and catch the bug both ways =="
fail=0
check_text() {
  local haystack="$1" label="$2" pattern="$3"
  if grep -q "$pattern" <<<"$haystack"; then echo "  ok: $label"; else echo "  MISSING: $label ($pattern)"; fail=1; fi
}
check() { check_text "$report" "$1" "$2"; }

# Consistency axis: singleton testimony is no longer a substantive discharge;
# the deliberately contradictory twin is still UNSAT.
check "consistency refuses singleton rows as vacuous"        "consistency check vacuous: single constraint has no sibling to contradict"
check "consistency catches the accuracy_score contradiction" "test assertions contradictory about callsite \`sklearn.metrics.accuracy_score"
check "witness package provenance red remains loud"          "lacks required provenance KIND"

# Witness axis: one WitnessPackageMemento over the suite. The package records
# the good rows as passed and the contradictory twin as failed; verify currently
# refuses package testimony until provenance-kind emission lands.
check "witness package names the failing test"               "witness-package"
"$VENV/bin/python" - <<'PY' || fail=1
import json, glob, sys
b = glob.glob(".sugar/witnesses/*.witness")
if not b:
    print("  MISSING: witness package")
    sys.exit(1)
out = {}
for line in open(b[0], "rb"):
    line = line.strip()
    if line:
        w = json.loads(line)
        out[w["test"].split("::")[-1]] = w["outcome"]
good_names = {
    "test_multilabel_accuracy_score_exact_rows",
    "test_multilabel_zero_one_loss_exact_rows",
    "test_mean_shift_zero_bandwidth_exact_row",
    "test_sklearn_testing_exact_scalar_row",
}
ok = all(out.get(name) == "passed" for name in good_names)
bad = out.get("test_multilabel_accuracy_score_contradiction") == "failed"
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
import json, sys
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
    Path(".verify.json").write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
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
vacuous_rows = [
    r
    for r in rows
    if r.get("status") == "refused"
    and "consistency check vacuous" in (r.get("reason") or "")
]
ok = require("durable verify keeps singleton rows refused as vacuous", len(vacuous_rows) >= 4) and ok

bad_rows = [
    r
    for r in matching_rows("sklearn.metrics.accuracy_score#euf#")
    if r.get("status") == "unsatisfied"
]
bad_reason = " ".join(str(r.get("reason") or "") for r in bad_rows)
ok = require(
    "durable verify preserves the accuracy_score contradiction",
    len(bad_rows) == 1 and "equals both" in bad_reason,
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
verified = any(w.get("verdict") == "verified" for w in witnesses)
ok = require("durable verify recomputes witness package", verified) and ok
summary_ok = (
    receipt.get("discharged") == 0
    and receipt.get("violations") == 1
    and receipt.get("refused") == 5
    and receipt.get("ok") is False
)
ok = require("durable verify summary is discharged=0 violations=1 refused=5 ok=false", summary_ok) and ok
sys.exit(0 if (ok and verified and summary_ok) else 1)
PY

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: sklearn proved correct rows; the contradictory test refused both ways."
else
  echo "FAIL: sugar did not produce the expected verdict."
  exit 1
fi
