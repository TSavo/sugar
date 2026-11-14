#!/usr/bin/env bash
# python-literal-base64: the encoding proof goes through the Rust CLI product
# path, not the Python RPC unit harness.
#
# GOOD twin: encodeBase64("abc") == "YWJj"
#   - python-lift emits the literal-call equality and the encodeBase64 universe.
#   - pytest-witness emits a witness package for the passing test.
#   - sugar prove discharges both rows from the durable .proof.
#
# BAD twin: encodeBase64("abc") == "AAAA"
#   - the same z3 path refuses the false equality.
#   - the witness package is honestly verified as content-addressed evidence,
#     but its body records the failed pytest outcome, so the claim stays red.
#   - a lying DISCHARGED stdout cannot flip the package-body outcome.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
source "$REPO/scripts/showcase-terminal-identity.sh"
RUST="$REPO/implementations/rust"
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST/target}"
BIN="$("$REPO/bin/sugarbin" --profile release)"
PYTHON_SRC="$REPO/implementations/python/sugar-lift-py-pytest-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src"
VENV="${PYTHON_LITERAL_BASE64_VENV:-/tmp/python-literal-base64-venv}"
SYSTEM_PYTHON="${PYTHON_LITERAL_BASE64_PYTHON:-$(command -v python3)}"
PYTHON="$SYSTEM_PYTHON"

echo "== resolve the bundled SMT compiler via sugarbin =="
"$REPO/bin/sugarbin" --profile release --bin sugar-ir-smt-lib >/dev/null || {
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
  "$PYTHON" - "$1" "$2" "$3" "$4" <<'PY'
import json
import sys

prove_path, twin, expect, prove_rc = sys.argv[1:5]
prove = json.load(open(prove_path, encoding="utf-8"))
prove_rc = int(prove_rc)

def row(doc, needle):
    matches = [r for r in doc.get("rows", []) if needle in str(r.get("property", ""))]
    if not matches:
        raise SystemExit(f"FAIL({twin}): missing row containing {needle}")
    return matches[0]

assertion = row(prove, "#euf#")
witness = row(prove, "witness-package")
witness_verification = witness.get("verification") or {}

print(f"rows({twin}):")
for label, item in [
    ("prove assertion", assertion),
    ("prove witness", witness),
]:
    print(f"  {label:<17} {item.get('status'):<12} {item.get('reason', '')[:130]}")
print(f"  verdict={prove.get('verdict')} byStatus={prove.get('byStatus')}")

# The witness row is decided from the package body the proof states (step 9):
# a recomputed body carries `resolvedBy` on its witness verification.
if witness_verification.get("kind") != "witness" or not witness_verification.get("resolvedBy"):
    raise SystemExit(
        f"FAIL({twin}): the witness package body in the proof was not recomputed: {witness}"
    )

if expect == "good":
    if prove_rc != 0:
        raise SystemExit(f"FAIL({twin}): expected prove exit 0, got {prove_rc}")
    if assertion.get("status") != "discharged" or witness.get("status") != "discharged":
        raise SystemExit(f"FAIL({twin}): expected discharged rows")
    if prove.get("verdict") != "green":
        raise SystemExit(f"FAIL({twin}): prove verdict must be green, got {prove.get('verdict')}")
else:
    if prove_rc == 0:
        raise SystemExit(f"FAIL({twin}): bad twin must make prove exit nonzero")
    if assertion.get("status") != "unsatisfied" or witness.get("status") != "unsatisfied":
        raise SystemExit(f"FAIL({twin}): expected unsatisfied rows")
    if prove.get("verdict") != "refuted":
        raise SystemExit(f"FAIL({twin}): prove verdict must be refuted, got {prove.get('verdict')}")

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

  (cd "$dir" && showcase_run_with_terminal sugar.mint env PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" "$BIN" mint --out . --quiet) >/dev/null || {
    echo "FAIL($twin): mint"
    return 1
  }

  (cd "$dir" && PATH="$PYTHON_BIN_DIR:$PATH" PYTHONPATH="$PYTHON_SRC" \
    "$BIN" prove --allow-failed-components . --json) >"$dir/.prove.raw" 2>&1
  local prove_rc=$?
  extract_json_receipt "$dir/.prove.raw" "$dir/.prove.json" || return 1
  check_normal_receipts "$dir/.prove.json" "$twin" "$expect" "$prove_rc" || return 1

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
  echo "==== python-literal-base64: FAIL ===="
  exit 1
fi
echo "==== python-literal-base64: PASS ===="
echo "encodeBase64(\"abc\") is proved through sugar mint/prove with SMT, witness package verification, and lying-discharge guard."
[ -z "${SHOWCASE_SUBJECT_WITNESS:-}" ] || printf '%s\n' "${SHOWCASE_SUBJECT_ID:?}" > "$SHOWCASE_SUBJECT_WITNESS"
