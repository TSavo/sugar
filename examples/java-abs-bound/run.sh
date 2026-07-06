#!/usr/bin/env bash
# G2b × G2 showcase: comparison bound meets walked numeric universe.
#
# The industry belief: abs(x) >= 0 — stated as a bound, not an equality.
# No vendor test ever asserted this bound. Sugar adjudicates it anyway.
#
# G2 walks Math.abs(int)'s body `(a < 0) ? -a : a` → int32.eq-bv-expr universe row.
# G2b lifts assertTrue(abs(MIN_VALUE) >= 0) → >=(call:abs(MIN_VALUE), 0).
# bv32 contagion promotes >= to int32.gte-const (bvsge).
# Conjoined: bv32 body evaluates abs(MIN_VALUE) = -2^31 < 0. bvsge(-2^31, 0) = false.
# UNSAT → consistency unsatisfied.
#
# "No vendor test asserts any bound on abs(MIN_VALUE); the universe walked from
#  Math.java refutes abs >= 0 anyway." — the bound and the body meet at the same CID.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac  >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java   >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: G2b × G2 — comparison bound meets walked numeric universe."
echo "SCOPE: assertTrue(abs(MIN_VALUE) >= 0) — the industry belief, as a bound."
echo "SCOPE: No vendor test ever wrote this assertion."
echo "SCOPE: G2 universe: int32.eq-bv-expr(call:abs(MIN), bv32.ite(bv32.slt(a,0),bv32.neg(a),a))"
echo "SCOPE: G2b bound:   >=(call:abs(MIN), 0)  → int32.gte-const via bv32 contagion"
echo "SCOPE: Conjoined: bv32 evaluates abs(MIN)=-2^31; bvsge(-2^31, #x00000000) = false."
echo "SCOPE: UNSAT → unsatisfied. No vendor test needed — the walked body adjudicates it."

echo
echo "== resolve the sugar CLI via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: JavaTestAssertionsRpc.class not built"; exit 1; }

echo
echo "== prepare manifest and clean state =="
suite="bad"
dir="$HERE/$suite"
mfin="$dir/.sugar/lift/java-test-assertions/manifest.toml.in"
mf="$dir/.sugar/lift/java-test-assertions/manifest.toml"
sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
rm -rf "$dir/.sugar/runs" 2>/dev/null || true
rm -f "$dir"/.prove*.json "$dir"/.verify*.json 2>/dev/null || true

echo
echo "── suite: $suite ──"

echo "-- mint --"
( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1 || { echo "FAIL[$suite]: sugar mint failed"; exit 1; }

have_proof=0
for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
[ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

# Verify int32.eq-bv-expr universe row is in the proof (teeth check).
strings "$dir"/blake3-512_*.proof | grep -q 'int32.eq-bv-expr' || {
  echo "FAIL[$suite]: no int32.eq-bv-expr universe row in minted .proof"
  exit 1
}
echo "   int32.eq-bv-expr universe row present (walked Math.abs body)"

echo "-- prove --"
prove_json="$dir/.prove.json"
( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

consistency_status="$(python3 - "$REPO" "$prove_json" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

rows = load_receipt(sys.argv[2]).get('rows', [])
c = [r.get('status') for r in rows if 'consistency' in (r.get('property') or '')]
print(','.join(c) if c else 'MISSING')
PY
)"
echo "   consistency: $consistency_status"

if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
  echo "FAIL[$suite]: expected consistency unsatisfied, got: $consistency_status"
  exit 1
fi

echo "-- verify: durable artifact --"
verify_json="$dir/.verify.json"
( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json 2>/dev/null ) > "$verify_json" || true

python3 - "$REPO" "$suite" "$verify_json" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

suite, path = sys.argv[2], sys.argv[3]
receipt = load_receipt(path)
rows = receipt.get("rows", [])
consistency = [
    r.get("status")
    for r in rows
    if (r.get("property") or "").startswith("consistency:")
]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if "unsatisfied" not in consistency:
    raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
print(f"   durable consistency: {','.join(consistency)}")
print(f"   durable: PASS (industry belief abs(MIN)>=0 refuted by walked body)")
print(f"            no vendor test ever wrote this bound; Math.abs body adjudicates it.")
PY

echo
echo "== java-abs-bound showcase: PASS =="
