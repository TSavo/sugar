#!/usr/bin/env bash
# java-abs-flagship showcase: the stdlib flagship.
#
# SOURCE: the JDK's OWN test file AbsTests.java (verbatim, unmodified).
#         https://raw.githubusercontent.com/openjdk/jdk/master/test/jdk/java/lang/Math/AbsTests.java
#         PROVENANCE.md has the exact sha256 and upstream URL.
#
# SCOPE: source is the JDK's own AbsTests.java, verbatim; line 110 discharges
#        abs(MIN)==MIN; the industry belief abs>=0 is refuted by the JDK's own body.
#
# THE MIC DROP:
#   Line 110 of AbsTests.java (JDK comments: "// Strange but true"):
#     errors += testIntAbs(Math::abs, Integer.MIN_VALUE, Integer.MIN_VALUE);
#   This is the JDK asserting: abs(MIN_VALUE) == MIN_VALUE.
#   The industry believes abs(x) >= 0. The JDK's own body proves it wrong.
#
# LIFT PATHWAY (P6 — error-sentinel, NO name keys):
#   The kit walks the body of testIntAbs STRUCTURALLY:
#     result = absFunc.applyAsInt(argument);
#     if (result != expected) { ... return 1; }  <- guard: != -> relation: =
#     else { return 0; }
#   Classification: equality assertion (result must EQUAL expected).
#   No method name enters the classification — body shape only.
#
#   At the callsite: Math::abs resolves to callee "abs" (MemberReferenceTree).
#   Integer.MIN_VALUE resolves to -2147483648 (platform-axioms.json, JLS §4.2.1).
#   Lifted contract: =(call:abs(-2147483648), -2147483648)
#
# G2 NUMERIC UNIVERSE (walked, not hand-authored):
#   Math.abs(int) body in vendor/jdk21/java/lang/Math.java:
#     return (a < 0) ? -a : a;
#   Walked BV expression: bv32.ite(bv32.slt(a,0), bv32.neg(a), a)
#   At a=-2147483648: bv32.neg(-2^31) = -2^31 (two's complement overflow).
#   z3 BV theory: DISCHARGE for abs(MIN)==MIN; UNSAT for abs(MIN)==MAX.
#
# GOOD suite: good/src/jtreg/AbsTests.java (the JDK's own test, verbatim)
#   Lifts line 110: =(abs(MIN), MIN) + int32.eq-bv-expr universe.
#   Conjoined: SAT -> consistency discharged.
#
# BAD suite: bad/src/test/java/demo/AbsFlagshipBadTest.java
#   assertEquals(2147483647, abs(-2147483648)) -- the industry belief.
#   Lifts: =(abs(MIN), MAX) + int32.eq-bv-expr universe.
#   Conjoined: UNSAT -> consistency unsatisfied.
#   The refutation is from the JDK's own walked body.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
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

echo "SCOPE: java-abs-flagship — source is the JDK's own AbsTests.java, verbatim."
echo "SCOPE: Line 110 discharges abs(MIN)==MIN (JDK comments: '// Strange but true')."
echo "SCOPE: The industry belief abs(x)>=0 is refuted by the JDK's own Math.abs body."
echo "SCOPE: P6 lift pathway: error-sentinel harness classification, NO name keys."
echo "SCOPE: Integer.MIN_VALUE resolved from platform-axioms.json (JLS §4.2.1)."

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

pyget() { python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print($2)" "$1"; }

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "── suite: $suite (expect consistency: $expect_consistency) ──"

  echo "-- mint --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1 || { echo "FAIL[$suite]: sugar mint failed"; exit 1; }

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # The numeric-universe row must be in the minted proof: an int32.eq-bv-expr atom.
  # No row = no teeth.
  python3 - "$suite" "$dir" <<'PY'
import glob, json, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    if b"int32.eq-bv-expr" in open(p, "rb").read():
        found = True
        break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no int32.eq-bv-expr numeric-universe row in any minted .proof")
print(f"   numeric-universe row (int32.eq-bv-expr) present in minted .proof")
PY

  echo "-- prove: consistency rows (equality ^ int32.eq-bv-expr conjoined per #euf# name) --"
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
    print(f"   durable: PASS (JDK's own AbsTests.java line 110 discharges abs(MIN)==MIN)")
    print(f"            Source: JDK AbsTests.java verbatim. '// Strange but true' — proved.")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (industry belief abs(MIN)==MAX refuted;")
    print(f"            bv32.ite(bv32.slt(a,0),bv32.neg(a),a) at a=MIN_VALUE = MIN_VALUE)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-abs-flagship showcase: PASS =="
echo "   Source: JDK's own AbsTests.java (verbatim). The language tests its own stdlib."
echo "   Line 110 ('// Strange but true'): abs(MIN_VALUE)==MIN_VALUE. Discharged."
echo "   Industry belief abs(x)>=0: REFUTED by the walked body."
