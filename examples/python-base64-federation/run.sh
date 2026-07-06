#!/usr/bin/env bash
# python-base64-federation: base64 as a VENDOR, a separate CONSUMER, sat/unsat by
# conjoining three facts through the .proof -- the cross-project federation.
#
#   VENDOR  (vendor/b64vendor.py): defines encodeBase64 and swears
#           encodeBase64("abc") == "YWJj".  `sugar mint` lifts the body to the
#           str.eq-bv-blocks universe and packages it + the sworn fact into a
#           content-addressed .proof.
#   CONSUMER stages the vendor .proof in .sugar/imports/ and writes its OWN unit
#           test about an input the vendor never swore.  `sugar prove` conjoins:
#             (1) the vendor's sworn fact   eq(call:encodeBase64("abc"), "YWJj")
#             (2) the vendor's universe     str.eq-bv-blocks(encodeBase64 body)
#             (3) the consumer's fact       eq(call:encodeBase64("xyz"), <claim>)
#           via the dig's ambient-post specialization on call:encodeBase64 -- and
#           z3 decides SAT/UNSAT WITHOUT re-deriving base64.
#
#   GOOD consumer: encodeBase64("xyz") == "eHl6" (correct) -> SAT -> discharged.
#   BAD  consumer: encodeBase64("xyz") == "AAAA" (wrong)   -> UNSAT -> unsatisfied.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST/target}"
BIN="$("$REPO/bin/sugarbin" --profile release)"
PYTHON_SRC="$REPO/implementations/python/sugar-lift-py-pytest-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src"
VENV="${PYTHON_LITERAL_BASE64_VENV:-/tmp/python-literal-base64-venv}"
SYSTEM_PYTHON="${PYTHON_LITERAL_BASE64_PYTHON:-$(command -v python3)}"
PYTHON="$SYSTEM_PYTHON"

echo "== build the bundled SMT compiler =="
cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib >/dev/null || { echo "FAIL: SMT compiler build"; exit 1; }
[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required for this showcase"; exit 1; }

if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3, cbor2, nacl, pytest
PY
then
  PYTHON="$VENV/bin/python"
  [ -x "$PYTHON" ] || "$SYSTEM_PYTHON" -m venv "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl pytest
fi
PYTHON_BIN_DIR="$(cd "$(dirname "$PYTHON")" && pwd)"

VENDOR="$HERE/vendor"

clean() { local d="$1"; find "$d" -maxdepth 1 -name 'blake3-512_*.proof' -delete 2>/dev/null
  rm -rf "$d/.sugar/runs" "$d/.sugar/witnesses" "$d/__pycache__" "$d/.pytest_cache" 2>/dev/null
  rm -f "$d"/.prove*.json "$d"/.prove*.raw 2>/dev/null; }

echo
echo "==================== VENDOR mints its .proof ===================="
clean "$VENDOR"
(cd "$VENDOR" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$VENDOR:$PYTHON_SRC" "$BIN" mint --out . --quiet) >/dev/null || {
  echo "FAIL: vendor mint"; exit 1; }
VENDOR_PROOF="$(ls "$VENDOR"/blake3-512_*.proof 2>/dev/null | head -1)"
[ -f "$VENDOR_PROOF" ] || { echo "FAIL: vendor produced no .proof"; exit 1; }
echo "vendor .proof: $(basename "$VENDOR_PROOF")"

check_consumer() {
  local twin="$1" expect="$2"
  local dir="$HERE/consumer-$twin"
  echo
  echo "==================== CONSUMER: $twin (expect: $expect) ===================="
  clean "$dir"
  mkdir -p "$dir/.sugar/imports"
  rm -f "$dir/.sugar/imports/"*.proof
  cp "$VENDOR_PROOF" "$dir/.sugar/imports/"
  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$dir:$VENDOR:$PYTHON_SRC" "$BIN" mint --out . --quiet) >/dev/null || {
    echo "FAIL($twin): consumer mint"; return 1; }
  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$dir:$VENDOR:$PYTHON_SRC" \
    "$BIN" prove --allow-failed-components . --json) >"$dir/.prove.raw" 2>&1
  local rc=$?
  "$PYTHON" - "$dir/.prove.raw" "$twin" "$expect" "$rc" <<'PY'
import json, re, sys
raw, twin, expect, rc = sys.argv[1:5]
text = re.sub(r"\x1b\[[0-9;]*m", "", open(raw, encoding="utf-8", errors="replace").read())
dec = json.JSONDecoder()
doc = None
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, _ = dec.raw_decode(text[i:])
    except Exception:
        continue
    if isinstance(obj, dict) and "rows" in obj:
        doc = obj
        break
if doc is None:
    print(f"FAIL({twin}): no JSON receipt"); raise SystemExit(1)
rows = [r for r in doc["rows"] if "#euf#" in str(r.get("property", ""))]
if not rows:
    print(f"FAIL({twin}): no #euf# conjoin row"); raise SystemExit(1)
# the CONSUMER's claim is keyed on its own input "xyz" (the vendor's own row is
# keyed on "abc"); select the consumer row to report the conjoin verdict.
consumer = [r for r in rows if "xyz" in str(r.get("property", ""))]
row = consumer[0] if consumer else rows[0]
viol = doc.get("violations") or 0
print(f"  consumer conjoin row: {row.get('status')}  {row.get('reason','')[:110]}")
print(f"  totals: discharged={doc.get('discharged')} violations={viol}")
if expect == "PROVEN":
    ok = row.get("status") == "discharged" and viol == 0 and int(rc) == 0
else:
    ok = row.get("status") == "unsatisfied" and viol >= 1 and int(rc) != 0
print(("OK" if ok else "FAIL") + f"({twin}): expected {expect}")
raise SystemExit(0 if ok else 1)
PY
}

fail=0
check_consumer good PROVEN || fail=1
check_consumer bad  REFUSED || fail=1

echo
if [ "$fail" -ne 0 ]; then echo "==== python-base64-federation: FAIL ===="; exit 1; fi
echo "==== python-base64-federation: PASS ===="
echo "A consumer's claim about base64 is decided SAT/UNSAT by conjoining the vendor's"
echo "fact + universe (from the staged .proof) with the consumer's fact -- no re-derivation."
