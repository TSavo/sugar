#!/usr/bin/env bash
# java-voltron showcase: Voltron — mutually-recursive construction-semantics resolver.
#
# WHAT IS WALKED:
#   The receiver `w.unwrap()` is itself a call; resolving it walks Wrapper's
#   ctor→field→getter to the inner `new Box(5)`, then Box's ctor→field→getter
#   to 5 — two layers, from source, no execution. The BAD is a single assertion
#   refuted solely by the two-layer construction.
#
#   Layer 1 edges (Wrapper):
#     1. MethodInvocationTree: receiver w.unwrap() detected as chained call
#     2. IdentifierTree "w" in ssaBindings → NewClassTree new Wrapper(new Box(5))
#     3. ClassTree(Wrapper): receiver class indexed from workspace
#     4. MethodTree(unwrap): exactly one non-static match, arity 0
#     5. ReturnTree: body is exactly one `return this.box;`
#     6. MemberSelectTree: return expression is this.box → field name "box"
#     7. VariableTree(box): field declaration with Modifier.FINAL
#     8. MethodTree(ctor Wrapper(Box b)): arity matches ctorArgs.size()
#     9. AssignmentTree: `this.box = b` → param index 0
#    10. ctorArgs.get(0) = new Box(5) → recurse
#
#   Layer 2 edges (Box, inside resolveIntFromChain):
#    11. ClassTree(Box): looked up from resolved ResolvedCtor
#    12. MethodTree(get): exactly one non-static match, arity 0
#    13. ReturnTree: body is exactly one `return this.value;`
#    14. MemberSelectTree: return expression is this.value → field name "value"
#    15. VariableTree(value): field declaration with Modifier.FINAL
#    16. MethodTree(ctor Box(int v)): arity matches ctorArgs.size()
#    17. AssignmentTree: `this.value = v` → param index 0
#    18. ctorArgs.get(0) = 5 → asIntLiteral → 5
#
# HONEST SCOPE (weak tier):
#   Only pure single-return-of-final-field getters are supported at every layer.
#   Any impurity ANYWHERE in the chain refuses the whole assertion by name.
#   Any of the following causes a named REFUSAL (not a falsePass):
#     - field not declared final at any layer
#     - field assigned outside a constructor at any layer
#     - getter body has more than one statement at any layer
#     - return expression is computation at any layer (e.g. return this.value + 1)
#     - constructor argument at the leaf is not an int literal
#     - chain depth exceeds 8 hops
#   Refusal keeps the opaque term unconstrained (existing P5c behaviour).
#
# THE ASYMMETRY THAT MATTERS:
#   The BAD test has a SINGLE assertion (assertEquals(6, w.unwrap().get())) and NO
#   internal contradiction. Without the construction operand it would wrongly
#   discharge — the opaque term call:get(w.unwrap__) can equal anything.
#   With it: =(get(w.unwrap__),5) [two-layer ctor pin] ∧ =(get(w.unwrap__),6) [test claim]
#   → UNSATISFIED. The refutation comes solely from Box's ctor, crossed via Wrapper's field.
#
# GOOD suite:
#   - testTwoLayerChain: assertEquals(5, w.unwrap().get()) where Wrapper(Box(5)) pins==5
#     → discharged.
#
# BAD suite:
#   - testTwoLayerChainWrongValue: assertEquals(6, w.unwrap().get())
#     SINGLE assertion, refuted by the two-layer construction — no within-test contradiction.
#
# Runs sugar mint → sugar prove → sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: Voltron — mutually-recursive construction-semantics resolver."
echo "SCOPE: The receiver w.unwrap() is itself a call; resolving it walks Wrapper's"
echo "SCOPE: ctor->field->getter to the inner new Box(5), then Box's ctor->field->getter"
echo "SCOPE: to 5 — two layers, from source, no execution."
echo "SCOPE: The BAD is a single assertion refuted solely by the two-layer construction."
echo "SCOPE: Weak tier: pure final-field getters only; any impurity anywhere refuses the whole chain."

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

  echo "-- mint: lift Java test assertions --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

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
    print(f"   durable: PASS (consistent — two-layer construction pin agrees with test claim)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (contradiction detected — refuted by two-layer construction: pin=5, claim=6)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-voltron showcase: PASS =="
