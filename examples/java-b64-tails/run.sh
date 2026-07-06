#!/usr/bin/env bash
# java-b64-tails showcase: THE STRONG TIER, MADE TOTAL (paper 26 PHASE 2).
#
# java-b64-strong walks multiple-of-3 inputs (whole 3-byte blocks). This
# showcase closes its declared PHASE-2 gap: the mod-3 TAILS. A 1-byte or 2-byte
# leftover packs into the work area and emits 2 or 3 sextet chars + 1 or 2 '='
# pad bytes (Base64.java:737-760). We walk the tail sextet index expressions
# THROUGH THE SAME symbolic interpreter as the full block; the '=' pad codepoint
# is resolved from the vendor AST (PAD_DEFAULT, BaseNCodec.java:179), never
# typed; the pad COUNT is the literal's length mod 3.
#
# THE MARQUEE (bad twin): assertEquals("YmX=", encode("ba")). "YmX=" is WRONG
# (the correct value is "YmE=") but ALPHABET-VALID -- Y, m, X are all in the
# standard table and '=' is the sworn pad, so the WEAK tier alone DISCHARGES it.
# Only the tail equations refute it. That refutation, over a PADDED lie, is the
# entire point of this build.
#
# WHAT IS WALKED (Base64.java, tag rel/commons-codec-1.16.1), with tree provenance:
#   work = (work << 8) + b                                  (line 778; accumulation)
#   -- 2-byte tail (case 2) --
#   out0 = encodeTable[work >> 10 & MASK_6BITS]             (line 753)
#   out1 = encodeTable[work >>  4 & MASK_6BITS]             (line 754)
#   out2 = encodeTable[work <<  2 & MASK_6BITS]             (line 755)
#   pad  = pad   when encodeTable == STANDARD_ENCODE_TABLE  (lines 757-758)
#   -- 1-byte tail (case 1) --
#   out0 = encodeTable[work >> 2 & MASK_6BITS]              (line 742)
#   out1 = encodeTable[work << 4 & MASK_6BITS]              (line 744)
#   pad  = pad pad  when encodeTable == STANDARD_ENCODE_TABLE (lines 746-748)
#   MASK_6BITS = 0x3f                                       (line 129)
#   pad <- PAD_DEFAULT = '=' = 61                           (BaseNCodec.java:179)
# Every shift, the mask, the 64 table codepoints AND the pad value trace to AST
# nodes. The SMT emitter contains no Base64 knowledge of its own.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON
# receipts. Verdicts come from parsed consistency-row statuses, not exit codes.
# The DERIVE step runs `sugar derive` over the minted tail atom and z3 computes
# the output STRING "YmE=" -- derived, not executed.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: java-b64-tails -- THE STRONG TIER MADE TOTAL (paper 26 PHASE 2)."
echo "SCOPE: the mod-3 tails (1/2-byte leftover + '=' pad), walked from the encode body."
echo "SCOPE: INPUT: 'ba' (2-byte tail) -> standard b64 'YmE=' (3 sextet + 1 pad)."
echo "SCOPE: GOOD: correct claim 'YmE='; tail equations + AST-resolved pad compute it; discharged."
echo "SCOPE: BAD:  'YmX=' is WRONG but ALPHABET-VALID; weak tier discharges it;"
echo "SCOPE:       only the tail equations refute it; unsatisfied."

echo
echo "== THE DOG THAT DID NOT BARK =="
echo "-- proving 'ba' encode is untested HERE: grep vendored source for the literal 'YmE' --"
if grep -r 'YmE' \
      "$HERE/good/vendor/commons-codec/" \
      "$HERE/bad/vendor/commons-codec/" \
      2>/dev/null | grep -v '^Binary'; then
  echo "FAIL: vendor source contains 'YmE' -- a point vector, not a universe"
  exit 1
fi
echo "   no vendor sample pins encode('ba'); the refutation is the equations', not a point's"

echo
echo "== resolve the sugar CLI via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
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

  echo "-- mint: lift assertion + WEAK (str.chars-in-set) + STRONG TAIL (str.eq-bv-blocks) rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # NON-REGRESSION: the WEAK row must still be present (str.chars-in-set).
  # TEETH: the STRONG TAIL row must be present, carrying pad_chars. Without the
  # tail equations the bad twin would discharge (alphabet-valid) -- vacuous.
  python3 - "$suite" "$dir" <<'PY'
import glob, sys, json, re
suite, dirp = sys.argv[1], sys.argv[2]
weak = strong = padded = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    b = open(p, "rb").read()
    if b"str.chars-in-set" in b: weak = True
    if b"str.eq-bv-blocks" in b: strong = True
    txt = b.decode("utf-8", "ignore")
    if re.search(r'pad_chars\\":\[61', txt): padded = True
if not weak:
    raise SystemExit(f"FAIL[{suite}]: weak str.chars-in-set row missing (regression)")
if not strong:
    raise SystemExit(f"FAIL[{suite}]: strong str.eq-bv-blocks row missing (no teeth)")
if not padded:
    raise SystemExit(f"FAIL[{suite}]: tail pad char (61='=') not pinned in payload")
print("   WEAK row present (str.chars-in-set) -- non-regression")
print("   STRONG TAIL row present (str.eq-bv-blocks) with pad_chars=[61] -- the tail equations + AST pad")
PY

  echo "-- prove: consistency rows (equality ^ weak ^ tail equations, conjoined per #euf# name) --"
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
    print(f"   durable: PASS (tail equations + AST pad compute 'YmE=' / 'Zg=='; claims consistent)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS")
    print(f"   the weak tier would discharge this padded lie; the tail equations refuted it.")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "==================== DERIVE: z3.model computes the padded output string ===================="
echo "-- extract the 2-byte-tail payload from the GOOD minted .proof and derive --"
PAYLOAD="$(python3 - "$HERE/good" <<'PY'
import glob, json, re, sys
dirp = sys.argv[1]
# Read the minted tail payload from the proof (the 2-byte-tail "ba" one, which
# carries pad_chars). NOTHING is recomputed -- read exactly as derive would.
payloads = set()
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    raw = open(p, "rb").read()
    if b"str.eq-bv-blocks" not in raw:
        continue
    txt = raw.decode("utf-8", "ignore")
    for m in re.finditer(r'"value":"(\{\\"input_bytes\\".*?\})"', txt):
        cand = json.loads('"' + m.group(1) + '"')
        d = json.loads(cand)
        if d.get("input_bytes") == [98, 97]:   # "ba"
            payloads.add(cand)
payloads = list(payloads)
if len(payloads) != 1:
    raise SystemExit(f"FAIL: expected exactly 1 'ba' tail payload in proof, found {len(payloads)}")
print(payloads[0])
PY
)"
[ -n "$PAYLOAD" ] || { echo "FAIL: could not extract tail payload"; exit 1; }

DERIVED="$("$SUGAR" derive --blocks-payload "$PAYLOAD" --quiet --json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["derived_string"])')"
echo "   sugar derive (z3.model over the minted tail equations + pad): \"$DERIVED\""
if [ "$DERIVED" != "YmE=" ]; then
  echo "FAIL: derive produced \"$DERIVED\", expected \"YmE=\""
  exit 1
fi
echo "   DERIVE: PASS (encode('ba') == \"YmE=\", derived from the walked tail + AST pad, not executed)"

echo
echo "== java-b64-tails showcase: PASS =="
echo "== the weak tier would discharge this padded lie; the tail equations refuted it. =="
