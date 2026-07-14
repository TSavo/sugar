#!/usr/bin/env bash
# java-testng-consistency showcase: Phase 4 of the Java-native lifter.
#
# THE PROOF: TestNG assertEquals(actual, expected) is REVERSED from JUnit.
# The VocabDeriver reads parameter NAMES from vendored TestNG Assert.java:
#   param[0]="actual" → TestNG order → expectedArgIndex=1 (expected is arg[1]).
# Hardcode JUnit order and TestNG lifts every assertion backwards.
# Vocabulary must be learned per-framework from its own source.
#
# assertion_source_dirs in .sugar/config.toml points at vendor/testng/
# (the vendored org.testng.Assert class from tag 7.10.2).
#
# GOOD suite:
#   - TestNGConsistencyTest:
#       Assert.assertEquals(g(2), 1) × 2  [TestNG order: actual=g(2), expected=1]
#       → =(call:g(2), 1) asserted twice
#       → consistent → all consistency rows: discharged
#
# BAD suite:
#   - TestNGContradictionTest:
#       Assert.assertEquals(g(2), 1)  → claim =(call:g(2), 1)
#       Assert.assertEquals(g(2), 2)  → claim =(call:g(2), 2)
#       Both share contract g#euf#c:callresult_g_a1(i:2)::assertion
#       Conjoin: =(g(2),1) ∧ =(g(2),2) → UNSAT
#       → consistency row: unsatisfied
#
# Runs sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
# JDK skip-guard: exits 0 with SKIP message if no JDK on PATH.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: Phase 4 Java-native lifter: TestNG assertEquals(actual, expected) — REVERSED from JUnit."
echo "SCOPE: VocabDeriver reads param names from vendored TestNG Assert.java: param[0]='actual' → index=1."
echo "SCOPE: GOOD: duplicate opaque assertions coalesce to one claim → refused as vacuous (PR #2813)."
echo "SCOPE: BAD:  Assert.assertEquals(g(2),1) + Assert.assertEquals(g(2),2) → unsatisfied."

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

  echo "-- mint: lift TestNG test assertions --"
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

  if [ "$expect_consistency" = "VACUOUS" ]; then
    if [ "$consistency_status" = "MISSING" ] || echo "$consistency_status" | grep -qv '^refused\(,refused\)*$'; then
      echo "FAIL[$suite]: expected only vacuity refusals, got: $consistency_status"
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
if expect_consistency == "VACUOUS":
    if any(s != "refused" for s in consistency):
        raise SystemExit(f"FAIL[{suite}]: expected only vacuity refusals, got {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (coalesced opaque claim refused per PR #2813)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (contradiction detected)")
PY
}

run_suite good VACUOUS
run_suite bad  REFUSE

echo
echo "== java-testng-consistency showcase: PASS =="
