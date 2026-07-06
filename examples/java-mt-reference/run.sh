#!/usr/bin/env bash
# java-mt-reference showcase: FLOOR rung — Mersenne Twister reference-vector point contracts.
#
# THESIS: new MersenneTwister(seed) is "seed(x).random()" — bin-1, a deterministic theorem;
# only the seed is IO. The vendor (Apache Commons RNG, rel/commons-rng-1.7,
# org.apache.commons.rng.core.source32.MersenneTwister) ships the original Matsumoto
# REFERENCE VECTORS in its own test suite: for seed {0x123, 0x234, 0x345, 0x456},
# MersenneTwisterTest.java::testMakotoNishimura asserts specific output values sourced from
#   http://www.math.sci.hiroshima-u.ac.jp/~m-mat/MT/MT2002/CODES/mt19937ar.out
# Those assertEquals(refValue, rng.nextInt()) ARE the sworn spec. We lift them as point
# contracts via the existing #euf# / location-keyed lift machinery — NO new kit machinery.
#
# SCOPE (state plainly):
#   FLOOR: proves the per-draw value is a contract the vendor SWORE (point equality,
#          bin-1, deterministic theorem for the fixed seed). Catches within-test contradiction.
#   NOT YET: does NOT refute a wrong-but-plausible reference value by derivation.
#             That requires the tempering universe + seed-state walk (rungs 2/3, following
#             the base64 strong-tier campaign). No derivation, no universe walk here.
#   LOGO: "Commons RNG's own Mersenne Twister reference vectors, lifted and federated —
#          the PRNG's per-draw contract, sworn by the vendor."
#
# GOOD suite:
#   MersenneTwisterReferenceTest.java — seed {0x123, 0x234, 0x345, 0x456}, 8 draws
#   each bound to an SSA local (draw1..draw8) and asserted to the vendor's sworn value.
#   All 8 point contracts are consistent (same value asserted once) → discharged.
#
# BAD suite:
#   MersenneTwisterContradictionTest.java — SAME seed, SAME draw[0] bound to draw1,
#   but asserted to TWO contradictory values in one test:
#     assertEquals(0x3fa23623, draw1)   // vendor-sworn correct value
#     assertEquals(0x12345678, draw1)   // false claim — contradiction
#   The location-keyed contract conjoins both → UNSAT → unsatisfied.
#
# Runs real sugar mint → sugar prove → sugar verify and parses real JSON receipts.
# Verdicts are read from consistency rows in the receipts, NOT from exit codes.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: FLOOR — MT reference-vector point contracts (bin-1, deterministic theorem)."
echo "SCOPE: Vendor: Apache Commons RNG rel/commons-rng-1.7 MersenneTwister."
echo "SCOPE: Reference values from Matsumoto http://www.math.sci.hiroshima-u.ac.jp/~m-mat/MT/MT2002/CODES/mt19937ar.out"
echo "SCOPE: GOOD: 8 sworn draws, each SSA-bound; consistent point contracts → discharged."
echo "SCOPE: BAD:  same draw[0], two contradictory assertEquals in one test → unsatisfied."
echo "SCOPE: NOT this showcase: derivation from algorithm (rung 2/3, tempering universe)."

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

  echo "-- mint: lift MT reference-vector point contracts --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # Verify the minted IR actually contains the reference-vector point contracts.
  # The #euf# / location-keyed contracts appear as ::assertion entries in the proof.
  python3 - "$suite" "$dir" <<'PY'
import glob, json, sys
suite, dirp = sys.argv[1], sys.argv[2]
found_ir = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    content = open(p, "rb").read()
    if b"::assertion" in content and b"nextInt" in content:
        found_ir = True
        break
if not found_ir:
    raise SystemExit(f"FAIL[{suite}]: no nextInt ::assertion contract in any minted .proof")
print(f"   reference-vector point contracts present in minted .proof")
PY

  echo "-- prove: consistency rows --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

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
    print(f"   durable: PASS (vendor-sworn reference vectors consistent)")
    print(f"   LOGO: Commons RNG's own MT reference vectors lifted and federated.")
    print(f"         Per-draw contract sworn by the vendor: bin-1, deterministic theorem.")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (within-test contradiction detected)")
    print(f"   Two contradictory assertions about draw[0] via same SSA local → UNSAT.")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-mt-reference showcase: PASS =="
