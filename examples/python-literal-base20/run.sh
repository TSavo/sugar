#!/usr/bin/env bash
# python-literal-base20: the encoding proof goes through the Rust CLI product
# path, not the Python RPC unit harness.
#
# GOOD twin: encode20("A") == "BE"
#   - python-lift emits the literal-call equality and the encode20 universe.
#   - pytest-witness emits a witness package for the passing test.
#   - sugar prove/verify discharge both rows from the durable .proof.
#
# BAD twin: encode20("A") == "AA"
#   - the same z3 path refuses the false equality.
#   - the witness package is honestly verified as content-addressed evidence,
#     but its body records the failed pytest outcome, so the claim stays red.
#   - a lying DISCHARGED stdout cannot flip the package-body outcome.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST/target}"
BIN="$("$REPO/bin/sugarbin" --profile release)"
PYTHON_SRC="$REPO/implementations/python/sugar-lift-py-pytest-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src"
VENV="${PYTHON_LITERAL_BASE64_VENV:-/tmp/python-literal-base20-venv}"
SYSTEM_PYTHON="${PYTHON_LITERAL_BASE64_PYTHON:-$(command -v python3)}"
PYTHON="$SYSTEM_PYTHON"

echo "== build the bundled SMT compiler =="
cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib >/dev/null || {
    echo "FAIL: SMT compiler build"
    exit 1
  }
[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required for this showcase"; exit 1; }

if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import nacl
import pytest
PY
then
  PYTHON="$VENV/bin/python"
  if [ ! -x "$PYTHON" ]; then
    "$SYSTEM_PYTHON" -m venv "$VENV"
  fi
  "$SYSTEM_PYTHON" -m venv --clear "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl pytest
fi
PYTHON_BIN_DIR="$(cd "$(dirname "$PYTHON")" && pwd)"

extract_json_receipt() {
  "$PYTHON" - "$1" "$2" <<'PY'
import json
import re
import sys

raw_path, out_path = sys.argv[1:3]
text = open(raw_path, encoding="utf-8", errors="replace").read()
text = re.sub(r"\x1b\[[0-9;]*m", "", text)
decoder = json.JSONDecoder()
for index, char in enumerate(text):
    if char != "{":
        continue
    try:
        obj, _ = decoder.raw_decode(text[index:])
    except Exception:
        continue
    if isinstance(obj, dict) and "rows" in obj:
        open(out_path, "w", encoding="utf-8").write(json.dumps(obj, indent=2, sort_keys=True))
        raise SystemExit(0)
print(f"FAIL: no JSON receipt in {raw_path}", file=sys.stderr)
raise SystemExit(1)
PY
}

check_normal_receipts() {
  "$PYTHON" - "$1" "$2" "$3" "$4" "$5" "$6" <<'PY'
import json
import sys

prove_path, verify_path, twin, expect, prove_rc, verify_rc = sys.argv[1:7]
prove = json.load(open(prove_path, encoding="utf-8"))
verify = json.load(open(verify_path, encoding="utf-8"))
prove_rc = int(prove_rc)
verify_rc = int(verify_rc)

def row(doc, needle):
    matches = [r for r in doc.get("rows", []) if needle in str(r.get("property", ""))]
    if not matches:
        raise SystemExit(f"FAIL({twin}): missing row containing {needle}")
    return matches[0]

assertion = row(prove, "#euf#")
witness = row(prove, "witness-package")
v_assertion = row(verify, "#euf#")
v_witness = row(verify, "witness-package")
dim = verify.get("witnessDimension") or {}
seen = dim.get("witnesses") or []

print(f"rows({twin}):")
for label, item in [
    ("prove assertion", assertion),
    ("prove witness", witness),
    ("verify assertion", v_assertion),
    ("verify witness", v_witness),
]:
    print(f"  {label:<17} {item.get('status'):<12} {item.get('reason', '')[:130]}")
print(f"  witness dimension total={dim.get('total')} ok={dim.get('ok')} verdicts={[w.get('verdict') for w in seen]}")

if dim.get("total") != 1 or dim.get("ok") is not True:
    raise SystemExit(f"FAIL({twin}): witnessDimension must verify exactly one witness package: {dim}")
if not seen or seen[0].get("verdict") != "verified":
    raise SystemExit(f"FAIL({twin}): durable witness body was not verified: {seen}")

if expect == "good":
    if prove_rc != 0 or verify_rc != 0:
        raise SystemExit(f"FAIL({twin}): expected prove/verify exit 0, got {prove_rc}/{verify_rc}")
    if assertion.get("status") != "discharged" or witness.get("status") != "discharged":
        raise SystemExit(f"FAIL({twin}): expected discharged rows")
    if v_assertion.get("status") != "discharged" or v_witness.get("status") != "discharged":
        raise SystemExit(f"FAIL({twin}): expected durable discharged rows")
    if verify.get("ok") is not True:
        raise SystemExit(f"FAIL({twin}): verify ok must be true")
else:
    if prove_rc == 0 or verify_rc == 0:
        raise SystemExit(f"FAIL({twin}): bad twin must make prove/verify exit nonzero")
    if assertion.get("status") != "unsatisfied" or witness.get("status") != "refused":
        raise SystemExit(f"FAIL({twin}): expected refused rows")
    if v_assertion.get("status") != "unsatisfied" or v_witness.get("status") != "refused":
        raise SystemExit(f"FAIL({twin}): expected durable refused rows")
    if verify.get("ok") is not False:
        raise SystemExit(f"FAIL({twin}): verify ok must be false")

print(f"OK({twin}): {expect}")
PY
}

check_lying_receipt() {
  "$PYTHON" - "$1" "$2" <<'PY'
import json
import sys

path, rc = sys.argv[1:3]
doc = json.load(open(path, encoding="utf-8"))
rc = int(rc)
rows = [r for r in doc.get("rows", []) if "witness-package" in str(r.get("property", ""))]
if not rows:
    raise SystemExit("FAIL(bad): lying-discharge run emitted no witness-package row")
row = rows[0]
print(f"  lying-discharge witness row: {row.get('status')} {row.get('reason', '')[:130]}")
if rc == 0:
    raise SystemExit("FAIL(bad): lying discharge made prove exit 0")
if row.get("status") != "unsatisfied":
    raise SystemExit(f"FAIL(bad): lying discharge flipped witness row: {row}")
reason = str(row.get("reason", ""))
if "outcomes failed" not in reason:
    raise SystemExit(f"FAIL(bad): witness refusal must come from package body, got {reason!r}")
print("OK(bad): lying DISCHARGED stdout did not flip the witness package")
PY
}

run_twin() {
  local twin="$1"
  local expect="$2"
  local dir="$HERE/$twin"

  echo
  echo "==================== twin: $twin (expect: $expect) ===================="
  find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -delete
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/__pycache__" "$dir/.pytest_cache"
  rm -f "$dir"/.prove*.json "$dir"/.prove*.raw "$dir"/.verify*.json "$dir"/.verify*.raw

  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" "$BIN" mint --out . --quiet) >/dev/null || {
    echo "FAIL($twin): mint"
    return 1
  }

  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" \
    "$BIN" prove --allow-failed-components . --json) >"$dir/.prove.raw" 2>&1
  local prove_rc=$?
  extract_json_receipt "$dir/.prove.raw" "$dir/.prove.json" || return 1

  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" \
    "$BIN" verify --allow-failed-components --project . --json) >"$dir/.verify.raw" 2>&1
  local verify_rc=$?
  extract_json_receipt "$dir/.verify.raw" "$dir/.verify.json" || return 1
  check_normal_receipts "$dir/.prove.json" "$dir/.verify.json" "$twin" "$expect" "$prove_rc" "$verify_rc" || return 1

  if [ "$twin" = "bad" ]; then
    mkdir -p "$dir/.sugar"
    cat > "$dir/.sugar/lying-discharge.sh" <<'SH'
#!/usr/bin/env sh
echo '{"verdict":"DISCHARGED","reason":"lying pytest discharge regression"}'
SH
    chmod +x "$dir/.sugar/lying-discharge.sh"
    (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" \
      SUGAR_WITNESS_DISCHARGE_PYTEST="$dir/.sugar/lying-discharge.sh" \
      "$BIN" prove --allow-failed-components . --json) >"$dir/.prove_lie.raw" 2>&1
    local lie_rc=$?
    extract_json_receipt "$dir/.prove_lie.raw" "$dir/.prove_lie.json" || return 1
    check_lying_receipt "$dir/.prove_lie.json" "$lie_rc" || return 1
  fi
}

fail=0
run_twin good good || fail=1
run_twin bad bad || fail=1

echo
if [ "$fail" -ne 0 ]; then
  echo "==== python-literal-base20: FAIL ===="
  exit 1
fi
echo "==== python-literal-base20: PASS ===="
echo "encode20(\"A\") is proved through sugar mint/prove/verify with SMT, witness package verification, and lying-discharge guard."
