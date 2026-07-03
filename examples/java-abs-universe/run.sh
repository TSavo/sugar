#!/usr/bin/env bash
# java-abs-universe showcase: G2 — numeric universe walked from the JDK vendor source.
#
# THE MARQUEE: the industry believes abs(x) >= 0.  That belief is false.
#
# Under JLS §4.2.1 Java int is 32-bit two's complement — a COMPILER AXIOM.
# Math.abs(int) body (jdk-21+35, sha256 in PROVENANCE.md):
#
#     return (a < 0) ? -a : a;
#
# Under two's complement: -Integer.MIN_VALUE == Integer.MIN_VALUE == -2147483648.
# Therefore: abs(-2147483648) == -2147483648.
#
# The kit walks the JDK source AST letter-for-letter and emits:
#   int32.eq-bv-expr(call:abs(a), bv32.ite(bv32.slt(a,0), bv32.neg(a), a))
#
# No arithmetic is hand-authored in the kit.  Every operator traces to a tree
# node in vendor/jdk21/java/lang/Math.java (LiteralTree, BinaryTree, UnaryTree,
# ConditionalExpressionTree).  z3's bitvector theory evaluates this at a=-2^31.
#
# GOOD suite:
#   assertEquals(-2147483648, abs(-2147483648))
#   Lifts equality + int32.eq-bv-expr under the same #euf# name.
#   Conjoined: SAT → discharged.  Nobody believes it.  Sugar proves it.
#
# BAD suite:
#   assertEquals(2147483647, abs(-2147483648))  ← the industry belief
#   The BV expression evaluates to -2147483648, not 2147483647.
#   Conjoined: UNSAT → unsatisfied.  The refutation comes from the walked body.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: G2 numeric-universe-walk — int32.eq-bv-expr contracts walked from JDK Math.abs body."
echo "SCOPE: Walked body: (a < 0) ? -a : a  → bv32.ite(bv32.slt(a,0), bv32.neg(a), a)."
echo "SCOPE: GOOD: abs(MIN_VALUE)==MIN_VALUE — the industry-confounding truth; discharged by z3 BV."
echo "SCOPE: BAD:  abs(MIN_VALUE)==MAX_VALUE — the industry belief; unsatisfied by z3 BV theory."

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

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

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

  echo "-- prove: consistency rows (equality ∧ int32.eq-bv-expr conjoined per #euf# name) --"
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
    print(f"   durable: PASS (abs(MIN_VALUE)==MIN_VALUE is true under the walked BV body)")
    print(f"            Nobody believes it. Sugar proves it.")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (industry belief abs(MIN_VALUE)==MAX_VALUE refuted;")
    print(f"            bv32.ite(bv32.slt(a,0),bv32.neg(a),a) at a=MIN_VALUE = MIN_VALUE)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-abs-universe showcase: PASS =="
