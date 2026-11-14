#!/usr/bin/env bash
# itsdangerous-token-padding: the real-name logo for the python universe rung.
#
# itsdangerous (Flask's signing dependency) encodes tokens with
#
#     def base64_encode(string):
#         string = want_bytes(string)
#         return base64.urlsafe_b64encode(string).rstrip(b"=")
#
# rstrip is TOTAL: no output of base64_encode ever ends with '=' -- for any
# input, forever, by one byte literal in the vendor's own source. The lifter
# walks that shape (the no-suffix-chars family), reports its ∀⊨sample
# evidence honestly (the wheel ships no test corpus: 0 vendor vectors,
# stated on the universe record), and conjoins ¬suffix-of("=", subject)
# into the callsite's #euf# assertion.
#
# BAD twin: the token-padding confusion -- asserting the PADDED standard
# base64url value where itsdangerous' stripped tokens live (the classic
# JWT/token interop bug). equality ∧ ¬suffixof -> UNSAT, statically.
#
# Verdicts parsed from real .verify.json rows; the verdict FLIP is the
# vacuity witness (a universe that never met the equality would let both
# twins discharge).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
source "$REPO/scripts/showcase-terminal-identity.sh"
TARGET_DIR="${CARGO_TARGET_DIR:-$REPO/implementations/rust/target}"
BIN="$("$REPO/bin/sugarbin" --profile release)"

VENV="${ITSDANGEROUS_LOGO_VENV:-/tmp/itsdangerous-logo-venv}"
export ITSDANGEROUS_LOGO_VENV="$VENV"
PYTHON="$VENV/bin/python"
needs_python_env=0
if [ ! -x "$PYTHON" ]; then
  echo "== create venv + install the real vendor (itsdangerous) =="
  needs_python_env=1
elif ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import itsdangerous
import nacl
PY
then
  needs_python_env=1
fi
if [ "$needs_python_env" = "1" ]; then
  python3 -m venv --clear "$VENV"
  "$PYTHON" -m pip install -q itsdangerous blake3 cbor2 pynacl
fi
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import itsdangerous
import nacl
PY
then
  echo "FAIL: python venv does not import required packages after install" >&2
  exit 1
fi
"$PYTHON" -c "import itsdangerous; print('vendor:', 'itsdangerous', itsdangerous.__version__ if hasattr(itsdangerous,'__version__') else '(installed)')" || {
  echo "FAIL: vendor install"; exit 1; }

[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }

run_twin() {
  local twin="$1" expect="$2"
  local dir="$HERE/$twin"
  echo
  echo "==================== twin: $twin (expect: $expect) ===================="
  rm -f "$dir"/blake3-512_*.proof 2>/dev/null
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/__pycache__" 2>/dev/null
  rm -f "$dir"/.prove*.json "$dir"/.verify*.json 2>/dev/null

  ( cd "$dir" && showcase_run_with_terminal sugar.mint "$BIN" mint --out . ) >/dev/null || { echo "FAIL: mint ($twin)"; return 1; }
  ( cd "$dir" && "$BIN" prove --allow-failed-components . --json > .verify.json ) || true
  [ -s "$dir/.verify.json" ] || { echo "FAIL: no verify receipt ($twin)"; return 1; }

  EXPECT="$expect" TWIN="$twin" python3 - "$dir/.verify.json" <<'PY' || return 1
import json, os, sys
expect, twin = os.environ["EXPECT"], os.environ["TWIN"]
doc = json.load(open(sys.argv[1]))
found = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "base64_encode" in str(r.get("property", ""))
]
if not found:
    print(f"FAIL({twin}): no base64_encode property rows in receipt"); sys.exit(1)
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
decode = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "base64_decode" in str(r.get("property", ""))
]
if not decode:
    print(f"FAIL({twin}): no base64_decode property rows in receipt"); sys.exit(1)
decode_statuses = {s for _, s in decode}
print(f"base64_decode rows({twin}):")
for n, s in decode:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    decode_ok = decode_statuses & ok_words and not (decode_statuses & bad_words)
else:
    decode_ok = bool(decode_statuses & bad_words)
if not decode_ok:
    print(
        f"FAIL({twin}): expected base64_decode {expect}, "
        f"statuses={sorted(decode_statuses)}"
    )
    sys.exit(1)
package_getattr = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_package_getattr_missing_attr" in str(r.get("property", ""))
]
if not package_getattr:
    print(f"FAIL({twin}): no __getattr__ raises rows in receipt"); sys.exit(1)
package_getattr_statuses = {s for _, s in package_getattr}
print(f"__getattr__ rows({twin}):")
for n, s in package_getattr:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    package_getattr_ok = (
        package_getattr_statuses & ok_words
        and not (package_getattr_statuses & bad_words)
    )
else:
    package_getattr_ok = bool(package_getattr_statuses & bad_words)
if not package_getattr_ok:
    print(
        f"FAIL({twin}): expected __getattr__ {expect}, "
        f"statuses={sorted(package_getattr_statuses)}"
    )
    sys.exit(1)
derive = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "Signer.derive_key" in str(r.get("property", ""))
]
if not derive:
    print(f"FAIL({twin}): no Signer.derive_key property rows in receipt"); sys.exit(1)
derive_statuses = {s for _, s in derive}
print(f"derive_key rows({twin}):")
for n, s in derive:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    derive_ok = derive_statuses & ok_words and not (derive_statuses & bad_words)
else:
    derive_ok = bool(derive_statuses & bad_words)
if not derive_ok:
    print(
        f"FAIL({twin}): expected derive_key {expect}, "
        f"statuses={sorted(derive_statuses)}"
    )
    sys.exit(1)
serializer_kwargs = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "itsdangerous.serializer.Serializer@test_token_padding.py" in str(r.get("property", ""))
]
if not serializer_kwargs:
    print(f"FAIL({twin}): no Serializer constructor property rows in receipt"); sys.exit(1)
serializer_kwargs_statuses = {s for _, s in serializer_kwargs}
print(f"Serializer.signer_kwargs rows({twin}):")
for n, s in serializer_kwargs:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    signer_kwargs_ok = (
        serializer_kwargs_statuses & ok_words
        and not (serializer_kwargs_statuses & bad_words)
    )
else:
    signer_kwargs_ok = bool(serializer_kwargs_statuses & bad_words)
if not signer_kwargs_ok:
    print(
        f"FAIL({twin}): expected Serializer.signer_kwargs {expect}, "
        f"statuses={sorted(serializer_kwargs_statuses)}"
    )
    sys.exit(1)
load_payload = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_serializer_load_payload_bad_payload" in str(r.get("property", ""))
]
if not load_payload:
    print(f"FAIL({twin}): no Serializer.load_payload raises rows in receipt"); sys.exit(1)
load_payload_statuses = {s for _, s in load_payload}
print(f"Serializer.load_payload rows({twin}):")
for n, s in load_payload:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    load_payload_ok = load_payload_statuses & ok_words and not (load_payload_statuses & bad_words)
else:
    load_payload_ok = bool(load_payload_statuses & bad_words)
if not load_payload_ok:
    print(
        f"FAIL({twin}): expected Serializer.load_payload {expect}, "
        f"statuses={sorted(load_payload_statuses)}"
    )
    sys.exit(1)
urlsafe_load_payload = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_urlsafe_load_payload_bad_payload" in str(r.get("property", ""))
]
if not urlsafe_load_payload:
    print(f"FAIL({twin}): no URLSafeSerializerMixin.load_payload raises rows in receipt"); sys.exit(1)
urlsafe_statuses = {s for _, s in urlsafe_load_payload}
print(f"URLSafeSerializerMixin.load_payload rows({twin}):")
for n, s in urlsafe_load_payload:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    urlsafe_ok = urlsafe_statuses & ok_words and not (urlsafe_statuses & bad_words)
else:
    urlsafe_ok = bool(urlsafe_statuses & bad_words)
if not urlsafe_ok:
    print(
        f"FAIL({twin}): expected URLSafeSerializerMixin.load_payload {expect}, "
        f"statuses={sorted(urlsafe_statuses)}"
    )
    sys.exit(1)
validate_rows = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if ".validate@test_token_padding.py" in str(r.get("property", ""))
]
if len(validate_rows) != 2:
    print(f"FAIL({twin}): expected two validate rows, got {len(validate_rows)}")
    sys.exit(1)
print(f"validate rows({twin}):")
for n, s in validate_rows:
    print(f"  {s:14s} {n[:110]}")

def row_statuses(needle):
    statuses = {s for n, s in validate_rows if needle in str(n)}
    if not statuses:
        print(f"FAIL({twin}): no validate row matching {needle}")
        sys.exit(1)
    return statuses

signer_validate_statuses = row_statuses("itsdangerous.signer.Signer.validate")
timestamp_validate_statuses = row_statuses(
    "itsdangerous.timed.TimestampSigner.validate"
)
if twin == "bad":
    signer_validate_ok = bool(signer_validate_statuses & bad_words)
else:
    signer_validate_ok = (
        signer_validate_statuses & ok_words
        and not (signer_validate_statuses & bad_words)
    )
if not signer_validate_ok:
    print(
        f"FAIL({twin}): unexpected Signer.validate statuses="
        f"{sorted(signer_validate_statuses)}"
    )
    sys.exit(1)
timestamp_validate_ok = (
    timestamp_validate_statuses & ok_words
    and not (timestamp_validate_statuses & bad_words)
)
if not timestamp_validate_ok:
    print(
        f"FAIL({twin}): expected TimestampSigner.validate to discharge, "
        f"statuses={sorted(timestamp_validate_statuses)}"
    )
    sys.exit(1)
print(f"OK({twin}): {expect}")
PY
}

fail=0
run_twin good discharged || fail=1
run_twin bad refused || fail=1

echo
if [ "$fail" -ne 0 ]; then
  echo "==== itsdangerous-token-padding: FAIL ===="
  exit 1
fi
echo "==== itsdangerous-token-padding: PASS ===="
echo "the padded-token confusion refuted statically by one byte literal"
echo "(rstrip(b'=')) from itsdangerous' own source -- the real-name logo."
[ -z "${SHOWCASE_SUBJECT_WITNESS:-}" ] || printf '%s\n' "${SHOWCASE_SUBJECT_ID:?}" > "$SHOWCASE_SUBJECT_WITNESS"
