#!/usr/bin/env bash
# java-instance-universe showcase: G3 construction-semantics walk through `this`.
#
# WHAT IS WALKED:
#   The kit walks ctor→field→getter edges, all from com.sun.source.tree.* nodes:
#     1. NewClassTree: the construction expression (e.g. new Box(5))
#     2. ClassTree: the receiver class indexed from the workspace
#     3. MethodTree: the getter method (exactly one non-static match by name+arity)
#     4. ReturnTree: the body must be exactly one `return this.field;` statement
#     5. MemberSelectTree / IdentifierTree: the field named in the return
#     6. VariableTree: field declaration with Modifier.FINAL
#     7. MethodTree (ctor): `this.field = <param>` assigns param index N
#     8. NewClassTree.getArguments().get(N): the literal value at that index
#
# HONEST SCOPE (weak tier):
#   Only pure single-return-of-final-field getters are supported.
#   Any of the following causes a named REFUSAL (not a falsePass):
#     - field not declared final
#     - field assigned outside a constructor (mutation defeats the pin)
#     - getter body has more than one statement, or is not `return <expr>`
#     - return expression is computation (e.g. return this.value + 1)
#     - constructor argument is not an int literal
#   Refusal keeps the opaque term unconstrained (existing P5c behaviour).
#
# THE ASYMMETRY THAT MATTERS:
#   The BAD test has a SINGLE assertion (assertEquals(7, x.get())) and NO
#   internal contradiction. Without the construction operand it would wrongly
#   discharge — the opaque term call:get(x) can equal anything.
#   With it: =(call:get(x),5) [ctor pin] ∧ =(call:get(x),7) [test claim]
#   → UNSATISFIED. The refutation comes solely from Box's constructor.
#
# GOOD suite:
#   - testBoxGetValue: new Box(5).get() == 5 (ctor pin agrees) → discharged
#
# BAD suite:
#   - testBoxGetWrongValue: new Box(5).get() == 7 (contradicts ctor pin 5) → unsatisfied
#     SINGLE assertion, refuted by Box's own source — no within-test contradiction.
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

echo "SCOPE: G3 instance-universe — construction-semantics walk through this."
echo "SCOPE: Walker edges: NewClassTree→ClassTree→MethodTree(getter)→ReturnTree→MemberSelectTree→VariableTree(final field)→MethodTree(ctor)→param assignment→literal arg."
echo "SCOPE: Weak tier: pure single-return-of-final-field only; anything else refused by name."
echo "SCOPE: GOOD: assertEquals(5, x.get()) where new Box(5) pins x.get()==5 → discharged."
echo "SCOPE: BAD:  assertEquals(7, x.get()) — SINGLE assertion, no internal contradiction."
echo "SCOPE:       Refuted solely by Box's ctor: =(get(x),5) [ctor] ∧ =(get(x),7) [test] → UNSAT."
echo "SCOPE:       Without the construction operand this would wrongly discharge."

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
    print(f"   durable: PASS (consistent)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (contradiction detected — refuted by Box constructor)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-instance-universe showcase: PASS =="
