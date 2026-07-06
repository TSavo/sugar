#!/usr/bin/env bash
# java-urlsafe-seam showcase: the marquee of paper 26.
#
# THE CLAIM (paper 26, verbatim): "the bad twin asserts the URL-safe confusion
# on an input the vendor never tested and the real CLI returns unsatisfied."
#
# THE CONFUSION: a consumer calls Apache Commons Codec's standard
# encodeBase64String(...) and asserts an expectation containing URL-safe
# alphabet characters ('-'). The '-' replaces '+' in URL-safe base64 but
# is NOT a member of the STANDARD_ENCODE_TABLE walked from the vendor's
# source. The universe row refutes the false claim statically.
#
# INPUT CHOSEN: "provekit~seam"
#   Standard b64:  cHJvdmVraXR+c2VhbQ==  (contains '+')
#   URL-safe b64:  cHJvdmVraXR-c2VhbQ==  (contains '-', NOT in STANDARD table)
#   python3: base64.b64encode(b'provekit~seam').decode() == 'cHJvdmVraXR+c2VhbQ=='
#
# THE VENDOR NEVER TESTED "provekit~seam": grep over vendored commons-codec
# source returns no match -- confirmed below as the "dog that didn't bark."
#
# WEAK TIER, CALLSITE-LEVEL: the universe contract is
#   str.chars-in-set(encodeBase64String("provekit~seam"), <walked STANDARD_ENCODE_TABLE>)
# Every character of the table traces to a LiteralTree node in
# vendor/commons-codec/Base64.java (tag rel/commons-codec-1.16.1). The table
# selection (urlSafe=false chain) is walked by literal propagation through the
# vendor's own delegation chain -- no table name, no method name, no default
# is hand-authored in the kit.
#
# GOOD suite:
#   Consumer asserts the CORRECT standard encoding:
#     assertEquals("cHJvdmVraXR+c2VhbQ==", encodeBase64String(getBytesUtf8("provekit~seam")))
#   Equality row AND universe row conjoin: SAT -> discharged.
#   '+' IS in STANDARD_ENCODE_TABLE; all output chars are in the standard set.
#
# BAD suite:
#   Consumer asserts the URL-SAFE spelling -- the classic confusion:
#     assertEquals("cHJvdmVraXR-c2VhbQ==", encodeBase64String(getBytesUtf8("provekit~seam")))
#   '-' is NOT in STANDARD_ENCODE_TABLE. The universe row conjoins with the
#   equality and z3's string theory refutes it: UNSAT -> unsatisfied.
#   The refutation comes from the universe walked from the vendor's source,
#   gated by their samples -- the vendor never tested this input.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
# Verdicts come from parsed consistency-row statuses, not exit-code laundering.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: java-urlsafe-seam -- marquee of paper 26."
echo "SCOPE: G1 universe-walk -- output charset walked from STANDARD_ENCODE_TABLE."
echo "SCOPE: INPUT: 'provekit~seam' -- standard b64 'cHJvdmVraXR+c2VhbQ==', urlsafe 'cHJvdmVraXR-c2VhbQ=='."
echo "SCOPE: GOOD: correct standard-alphabet assertion on untested input; discharged."
echo "SCOPE: BAD:  URL-safe confusion on untested input ('-' not in STANDARD table); unsatisfied."

echo
echo "== THE DOG THAT DID NOT BARK =="
echo "-- proving the input is untested: grep vendored commons-codec for 'provekit~seam' --"
if grep -r 'provekit' \
      "$HERE/good/vendor/commons-codec/" \
      "$HERE/bad/vendor/commons-codec/" \
      2>/dev/null | grep -v '^Binary'; then
  echo "FAIL: vendor source contains 'provekit' -- input is not untested"
  exit 1
fi
echo "   no vendor test ever touched 'provekit~seam'"
echo "   the refutation is the universe's, not a point's"

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
echo "== prepare manifests and clean state =="
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml"
  sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift assertions + walked universe rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # The universe row must actually be IN the minted proof: a str.chars-in-set
  # atom whose charset traces to the vendor's STANDARD table.
  # No row = no teeth: the refutation claim is vacuous without it.
  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    if b"str.chars-in-set" in open(p, "rb").read():
        found = True
        break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no str.chars-in-set universe row in any minted .proof")
print(f"   universe row present in minted .proof (refutation is membership-driven)")
PY

  echo "-- prove: consistency rows (equality ^ universe conjoined per #euf# name) --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

  # Verdicts parsed from JSON consistency rows -- not exit-code laundering.
  local consistency_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:')]) or 'MISSING'
")"
  echo "   prove consistency statuses: $consistency_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency discharged, got: $consistency_status"
      exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency rows found"
      exit 1
    fi
  else
    if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency unsatisfied, got: $consistency_status"
      exit 1
    fi
  fi

  echo "-- verify: durable artifact --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json 2>/dev/null ) > "$verify_json" || true

  python3 - "$suite" "$expect_consistency" "$verify_json" <<'PY'
import json, sys
suite, expect_consistency, path = sys.argv[1], sys.argv[2], sys.argv[3]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
consistency = [
    r.get("status")
    for r in rows
    if (r.get("property") or "").startswith("consistency:")
]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect_consistency == "DISCHARGE":
    if any(s != "discharged" for s in consistency):
        raise SystemExit(f"FAIL[{suite}]: expected all discharged, got {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (standard-alphabet assertion consistent with the walked universe)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (URL-safe confusion refuted --")
    print(f"            '-' is not in STANDARD_ENCODE_TABLE;")
    print(f"            the vendor never tested 'provekit~seam';")
    print(f"            the refutation is the universe's, not a point's)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-urlsafe-seam showcase: PASS =="
