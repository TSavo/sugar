#!/usr/bin/env bash
# stdlib base64 padding logo dual-assert receipt (CI ratchet) + scope boundary.
#
# Second real-name logo after itsdangerous-token-padding. Ambient: closed strip
# not-suffix-of("=", out) on JWT-style unpadded_urlsafe_b64encode
# (base64.urlsafe_b64encode(data).rstrip(b"=")). Same #euf# key:
#
#   GOOD:            unpadded b"cHJvdmVraXQ"  -> unpadded_urlsafe_b64encode discharged
#   BAD:             padded   b"cHJvdmVraXQ=" -> unpadded_urlsafe_b64encode unsatisfied
#   WRONG-UNPADDED:  wrong last char, no "="  -> discharged (OUT OF SCOPE - not injectivity)
#
# The third twin is the #3956 discrimination boundary: closed ambient does not
# refute non-suffix corruption. See SCOPE.md.
#
# Slim CI gate: logo property + scope twin, from sugar prove --json.
# Real name = CPython stdlib base64 (no third-party vendor required).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"
PYTHON_SRC="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src"

# Prefer a durable venv outside noexec /tmp (reuse itsdangerous logo venv if set).
VENV="${STDLIB_BASE64_PADDING_LOGO_VENV:-${ITSDANGEROUS_LOGO_VENV:-/tmp/stdlib-base64-padding-logo-venv}}"
export STDLIB_BASE64_PADDING_LOGO_VENV="$VENV"
PYTHON="$VENV/bin/python"

needs_python_env=0
if [ ! -x "$PYTHON" ]; then
  needs_python_env=1
elif ! "$PYTHON" - <<'PYCHK' >/dev/null 2>&1
import blake3
import cbor2
import nacl
PYCHK
then
  needs_python_env=1
fi
if [ "$needs_python_env" = "1" ]; then
  echo "== create venv + install sugar lift deps (stdlib logo needs no vendor) =="
  python3 -m venv --clear "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl
fi
if ! "$PYTHON" - <<'PYCHK' >/dev/null 2>&1
import blake3
import cbor2
import nacl
PYCHK
then
  echo "FAIL: logo venv missing required packages after install" >&2
  exit 1
fi

[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required for the logo receipt"; exit 1; }

"$REPO/bin/sugarbin" --profile release --bin sugar-ir-smt-lib >/dev/null 2>&1 \
  || "$REPO/bin/sugarbin" --profile debug --bin sugar-ir-smt-lib >/dev/null 2>&1 \
  || true

export PATH="$(cd "$(dirname "$PYTHON")" && pwd):$PATH"
export PYTHONPATH="$PYTHON_SRC${PYTHONPATH:+:$PYTHONPATH}"

# Property needle in prove JSON rows (local helper wrapping stdlib base64).
PROPERTY_NEEDLE="unpadded_urlsafe_b64encode"

extract_json_receipt() {
  python3 - "$1" "$2" <<'PYEX'
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
        open(out_path, "w", encoding="utf-8").write(
            json.dumps(obj, indent=2, sort_keys=True)
        )
        raise SystemExit(0)
print(f"FAIL: no prove JSON receipt with rows in {raw_path}", file=sys.stderr)
raise SystemExit(1)
PYEX
}

run_logo_twin() {
  local twin="$1"
  local expect="$2"
  local dir="$HERE/$twin"

  echo
  echo "==================== logo twin: $twin (expect $PROPERTY_NEEDLE: $expect) ===================="
  find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -delete
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/__pycache__" "$dir/.pytest_cache"
  rm -f "$dir"/.prove*.json "$dir"/.prove*.raw "$dir"/.prove*.err

  (cd "$dir" && "$BIN" mint --out . ) >/dev/null || {
    echo "FAIL($twin): mint"
    return 1
  }

  (cd "$dir" && "$BIN" prove --allow-failed-components --json . ) \
    >"$dir/.prove.raw" 2>"$dir/.prove.err" || true
  extract_json_receipt "$dir/.prove.raw" "$dir/.prove.json" || {
    echo "FAIL($twin): could not parse sugar prove --json"
    tail -n 40 "$dir/.prove.err" 2>/dev/null || true
    return 1
  }

  EXPECT="$expect" TWIN="$twin" NEEDLE="$PROPERTY_NEEDLE" python3 - "$dir/.prove.json" <<'PYCHK' || return 1
import json
import os
import sys

expect = os.environ["EXPECT"]
twin = os.environ["TWIN"]
needle = os.environ["NEEDLE"]
doc = json.load(open(sys.argv[1], encoding="utf-8"))
found = [
    r
    for r in doc.get("rows", [])
    if needle in str(r.get("property", ""))
]
if not found:
    print(f"FAIL({twin}): no {needle} rows in prove receipt (vacuity)")
    for r in doc.get("rows", []):
        print(f"  other: {r.get('status', ''):14s} {str(r.get('property', ''))[:110]}")
    sys.exit(1)

print(f"{needle} rows({twin}):")
for r in found:
    print(f"  {r.get('status', ''):14s} {str(r.get('property', ''))[:110]}")

statuses = {str(r.get("status", "")) for r in found}
ok_words = {"discharged", "proven", "consistent", "sat"}
bad_words = {
    "unsatisfied",
    "refused",
    "unsat",
    "contradictory",
    "inconsistent",
    "violation",
    "violated",
}

if expect == "discharged":
    ok = bool(statuses & ok_words) and not (statuses & bad_words)
else:
    ok = "unsatisfied" in statuses or bool(statuses & bad_words)

if not ok:
    print(f"FAIL({twin}): expected {needle} {expect}, statuses={sorted(statuses)}")
    sys.exit(1)

if expect == "unsatisfied" and "unsatisfied" not in statuses and statuses & bad_words:
    print(
        f"WARN({twin}): {needle} is unsat-family {sorted(statuses)} "
        f"but not literal 'unsatisfied'"
    )

print(f"OK({twin}): {needle} {expect}")
PYCHK
}

echo "SCOPE: logo = padding/trailing-equals only (see SCOPE.md) - not full base64 injectivity"
echo "SCOPE: GOOD discharged / BAD unsatisfied / WRONG-UNPADDED discharged (out of scope)"
echo "vendor: CPython stdlib base64 (real-name logo #2)"
"$PYTHON" -c "import base64, sys; print('python:', sys.version.split()[0], 'base64:', getattr(base64, '__file__', '?'))"

fail=0
run_logo_twin good discharged || fail=1
run_logo_twin bad unsatisfied || fail=1
# #3956 boundary: non-suffix corruption stays consistent under closed strip ambient.
run_logo_twin wrong-unpadded discharged || fail=1

echo
if [ "$fail" -ne 0 ]; then
  echo "==== stdlib base64 padding logo receipt: FAIL ===="
  exit 1
fi
echo "==== stdlib base64 padding logo receipt: PASS ===="
echo "GOOD discharged; BAD unsatisfied (padding); WRONG-UNPADDED discharged (out of scope)."
