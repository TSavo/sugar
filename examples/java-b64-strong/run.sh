#!/usr/bin/env bash
# java-b64-strong showcase: THE STRONG TIER (paper 26, "THE seam between tiers").
#
# The weak tier (java-codec-universe, java-urlsafe-seam) asserts every output
# char is a MEMBER of the walked encode table -- a SET. It refutes only
# out-of-alphabet claims. The strong tier mints the PER-CHARACTER EQUATIONS --
# the output as a FUNCTION of the input bytes, walked from the vendor's encode
# body by symbolic execution.
#
# THE MARQUEE (bad twin): assertEquals("ZmFy", encode("bar")). "ZmFy" is WRONG
# (it is encode("foo")) but ALPHABET-VALID -- every char is in the standard
# table, so the WEAK tier alone DISCHARGES it. Only the block equations refute
# it. That refutation is the entire point of this build.
#
# WHAT IS WALKED (Base64.java, tag rel/commons-codec-1.16.1), with tree provenance:
#   work = (work << 8) + b                                  (line 778; accumulation)
#   out0 = encodeTable[work >> 18 & MASK_6BITS]             (line 780)
#   out1 = encodeTable[work >> 12 & MASK_6BITS]             (line 781)
#   out2 = encodeTable[work >>  6 & MASK_6BITS]             (line 782)
#   out3 = encodeTable[work       & MASK_6BITS]             (line 783)
#   MASK_6BITS = 0x3f                                       (line 129)
# Shifts (18/12/6/8), the mask, and the 64 table codepoints all trace to AST
# nodes. The SMT emitter contains no Base64 knowledge of its own.
#
# PHASE 1 SCOPE: full 3-byte blocks only (len % 3 == 0). "bar" is one block.
# The mod-3 tails (1/2-byte + '=' pad, Base64.java:740-760) are PHASE 2 and are
# REFUSED BY NAME, not faked -- a non-multiple-of-3 callsite gets the weak row
# only, with a diagnostic naming the tail as unwalked. See PROVENANCE.md.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON
# receipts. Verdicts come from parsed consistency-row statuses, not exit codes.
# The DERIVE step runs `sugar derive` over the minted strong-tier atom and z3
# computes the output STRING "YmFy" -- derived, not executed.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: java-b64-strong -- THE STRONG TIER, the seam between tiers (paper 26)."
echo "SCOPE: per-character block equations walked from the vendor encode body."
echo "SCOPE: INPUT: 'bar' (one full 3-byte block), standard b64 'YmFy'."
echo "SCOPE: GOOD: correct claim 'YmFy'; block equations compute it; discharged."
echo "SCOPE: BAD:  'ZmFy' is WRONG but ALPHABET-VALID; weak tier discharges it;"
echo "SCOPE:       only the block equations refute it; unsatisfied."

echo
echo "== THE DOG THAT DID NOT BARK =="
echo "-- proving 'bar' encode is untested HERE: grep vendored source for the literal 'YmFy' --"
if grep -r 'YmFy' \
      "$HERE/good/vendor/commons-codec/" \
      "$HERE/bad/vendor/commons-codec/" \
      2>/dev/null | grep -v '^Binary'; then
  echo "FAIL: vendor source contains 'YmFy' -- a point vector, not a universe"
  exit 1
fi
echo "   no vendor sample pins encode('bar'); the refutation is the equations', not a point's"

echo
echo "== build the sugar CLI =="
if [ "${JAVA_ASSERT_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: kit not built"; exit 1; }

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

  echo "-- mint: lift assertion + WEAK (str.chars-in-set) + STRONG (str.eq-bv-blocks) rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # NON-REGRESSION: the WEAK row must still be present (str.chars-in-set).
  # TEETH: the STRONG row must be present (str.eq-bv-blocks). Without the
  # strong row the bad twin would discharge (alphabet-valid) -- vacuous.
  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
weak = strong = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    b = open(p, "rb").read()
    if b"str.chars-in-set" in b: weak = True
    if b"str.eq-bv-blocks" in b: strong = True
if not weak:
    raise SystemExit(f"FAIL[{suite}]: weak str.chars-in-set row missing (regression)")
if not strong:
    raise SystemExit(f"FAIL[{suite}]: strong str.eq-bv-blocks row missing (no teeth)")
print("   WEAK row present (str.chars-in-set) -- non-regression")
print("   STRONG row present (str.eq-bv-blocks) -- the per-character equations")
PY

  echo "-- prove: consistency rows (equality ^ weak ^ strong, conjoined per #euf# name) --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

  local consistency_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:')]) or 'MISSING'
")"
  echo "   prove consistency statuses: $consistency_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected discharged, got: $consistency_status"; exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency rows found"; exit 1
    fi
  else
    if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected unsatisfied, got: $consistency_status"; exit 1
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
consistency = [r.get("status") for r in rows if (r.get("property") or "").startswith("consistency:")]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect_consistency == "DISCHARGE":
    if any(s != "discharged" for s in consistency):
        raise SystemExit(f"FAIL[{suite}]: expected all discharged, got {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (block equations compute 'YmFy'; claim consistent)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS")
    print(f"   ZmFy is alphabet-valid -- the weak tier alone would discharge it; the block equations refuted it.")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "==================== DERIVE: z3.model computes the output string ===================="
echo "-- extract the strong-tier payload from the GOOD minted .proof and derive --"
PAYLOAD="$(python3 - "$HERE/good" <<'PY'
import glob, json, re, sys
dirp = sys.argv[1]
# The minted .proof body is JSON text (with a small binary header). The
# strong-tier atom carries the payload as a String const whose `value` is the
# escaped block-equation JSON. Pull every such value out of the proof, unescape
# it, and de-dup. NOTHING is recomputed here -- the payload is read from the
# minted artifact, exactly as `sugar derive --from-proof` would.
payloads = set()
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    raw = open(p, "rb").read()
    if b"str.eq-bv-blocks" not in raw:
        continue
    txt = raw.decode("utf-8", "ignore")
    for m in re.finditer(r'"value":"(\{\\"input_bytes\\".*?\]\})"', txt):
        payloads.add(json.loads('"' + m.group(1) + '"'))
payloads = list(payloads)
if len(payloads) != 1:
    raise SystemExit(f"FAIL: expected exactly 1 strong-tier payload in proof, found {len(payloads)}")
print(payloads[0])
PY
)"
[ -n "$PAYLOAD" ] || { echo "FAIL: could not extract strong-tier payload"; exit 1; }

DERIVED="$("$SUGAR" derive --blocks-payload "$PAYLOAD" --quiet --json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["derived_string"])')"
echo "   sugar derive (z3.model over the minted block equations): \"$DERIVED\""
if [ "$DERIVED" != "YmFy" ]; then
  echo "FAIL: derive produced \"$DERIVED\", expected \"YmFy\""
  exit 1
fi
echo "   DERIVE: PASS (encode('bar') == \"YmFy\", derived from the walked equations, not executed)"

echo
echo "== java-b64-strong showcase: PASS =="
