#!/usr/bin/env bash
# java-assertion-consistency showcase: Phase 2 of the Java-native lifter.
#
# Phase 2: assertion vocabulary LEARNED from the framework's own source
# (org.junit.jupiter.api.Assertions) via JavacTask.parse(). No hardcoded meanings.
#
# The vendor/junit5/Assertions.java in each suite's workspace is the verbatim source
# from which VocabDeriver learns assertEquals=equality, assertNotEquals=inequality,
# assertEquals(float,float,float)=approximate (refused), etc.
#
# assertion_source_dirs in .sugar/config.toml points at vendor/junit5/.
#
# GOOD suite:
#   - ConsistencyTest: assertEquals(1,g(2)) × 2 → consistent → discharged (P1 case)
#   - VocabDrivenConsistencyTest: assertEquals(1,g(2)) ∧ assertNotEquals(2,g(2))
#       → =(g(2),1) ∧ ≠(g(2),2) → consistent (g(2)=1 satisfies both) → discharged
#
# BAD suite:
#   - ContradictionTest: assertEquals(1,g(2)) ∧ assertEquals(2,g(2)) → unsatisfied (P1 case)
#   - VocabDrivenContradictionTest: assertEquals(1,g(2)) ∧ assertNotEquals(1,g(2))
#       → =(g(2),1) ∧ ≠(g(2),1) → DIRECT =/≠ contradiction → unsatisfied
#
# Runs sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: Phase 2 Java-native lifter: vocab LEARNED from org.junit.jupiter.api.Assertions source."
echo "SCOPE: assertEquals, assertNotEquals, assertNull, assertNotNull classified from framework source."
echo "SCOPE: assertEquals(float,float,float) with delta REFUSED (approximate, not exact =)."
echo "SCOPE: GOOD: assertEquals+assertNotEquals consistent; discharged."
echo "SCOPE: BAD: assertEquals+assertNotEquals contradiction (same value); unsatisfied."

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
  # Clean old state
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

  # Parse consistency rows (exclude witness-package rows which won't exist here)
  local consistency_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:')]) or 'MISSING'
")"
  echo "   prove consistency statuses: $consistency_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    # All rows must be discharged; none unsatisfied
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency discharged, got: $consistency_status"
      exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency rows found"
      exit 1
    fi
  else
    # At least one unsatisfied row
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
    print(f"   durable: PASS (contradiction detected)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-assertion-consistency showcase: PASS =="
