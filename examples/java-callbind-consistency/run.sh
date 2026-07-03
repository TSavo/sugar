#!/usr/bin/env bash
# java-callbind-consistency showcase: P5c call-binding lift.
#
# P5c mirrors Python PATTERN 5 (_apply_value_scope_binding + _call_origin_from_expr):
#
#   DOMINANT REAL-VENDOR SHAPE:
#     Codec codec = new Codec();
#     int r = codec.encode(42);      // SSA binding
#     assertEquals(42, r);           // assert about the local
#
#   The local `r` is an effectively-final SSA alias for `codec.encode(42)`.
#   The kit substitutes `r` → `encode(codec, 42)` and emits a LOCATION-KEYED
#   ::assertion contract (not #euf#-federated) because the receiver `codec` is
#   a local variable — receiver-dependent calls may return different values for
#   different receivers, so cross-location unification is unsound.
#
#   Location key = callee@file::class::testMethod:receiverName → scoped to THIS
#   test method, not across tests.
#
# GOOD suite:
#   - testDefaultCodecEncode: Codec(0).encode(42)==42 → discharged
#   - testStrictCodecEncode:  Codec(1).encode(42)==42 → discharged
#   Two tests, two distinct location-keyed contracts, both consistent → all discharged.
#
# BAD suite:
#   - testContradiction: codec.encode(42)==42 AND codec.encode(42)==99
#     (two assertEquals in the same test, both about the same SSA local `r`)
#     → same location-keyed name, mint conjoins → =(encode(codec,42),42) ∧ =(encode(codec,42),99)
#     → unsatisfied (within-test contradiction).
#
# Runs sugar mint → sugar prove → sugar verify and parses real JSON receipts.
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

echo "SCOPE: P5c call-binding lift — the dominant real-vendor test shape."
echo "SCOPE: 'Codec codec = new Codec(); int r = codec.encode(42); assertEquals(42, r)'"
echo "SCOPE: SSA alias r → substituted to encode(codec,42) → location-keyed ::assertion."
echo "SCOPE: Instance-method calls on local receivers are NOT #euf#-federated (receiver-dependent)."
echo "SCOPE: GOOD: consistent instance-method assertions per test → discharged."
echo "SCOPE: BAD:  two contradictory assertions about same call in one test → unsatisfied."

echo
echo "== build the sugar CLI =="
if [ "${JAVA_CALLBIND_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
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
    print(f"   durable: PASS (contradiction detected)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-callbind-consistency showcase: PASS =="
