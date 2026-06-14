#!/usr/bin/env bash
# java-forall-loop showcase: Phase 3 of the Java-native lifter.
#
# Proves: a bounded for-loop emitted as a guarded universal (forall x. 0<=x<3 => g(x)==1)
# federates with the engine's ambient-forall rule to refute contradicting point-claims
# from OTHER contracts — zero additional kit code required.
#
# GOOD suite:
#   - ForallLoopTest: for(int x=0; x<3; x++) assertEquals(1,g(x))
#     → forall x:Int. (0<=x AND x<3) => g(x)==1
#     → universal alone is consistent → all consistency rows discharged
#
# BAD suite:
#   - Same loop → forall universal
#   - Plus testGAtTwoIsTwo: assertEquals(2, g(2)) → point-claim g(2)==2
#   → engine instantiates universal at x=2: g(2)==1, contradicts g(2)==2
#   → consistency row: unsatisfied (cross-contract federation via ambient rule)
#
# Runs: sugar mint -> sugar prove -> sugar verify, parses real JSON receipts.
# JDK skip-guard: exits 0 with SKIP message if no JDK on PATH.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
if [ -n "${JAVA_FORALL_SHOWCASE_TARGET_DIR:-}" ]; then
  TARGET_DIR="$JAVA_FORALL_SHOWCASE_TARGET_DIR"
elif [ "${CI:-0}" = "1" ]; then
  TARGET_DIR="$HERE/.target"
else
  TARGET_DIR="$RUST/target"
fi
BIN_DIR="$TARGET_DIR/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: Phase 3 Java-native lifter: bounded for-loop → forall x. (0<=x<3 => g(x)==1)."
echo "SCOPE: GOOD is the universal alone (consistent); BAD adds the in-range contradiction g(2)==2."
echo "SCOPE: BAD contradiction detected via engine ambient-forall rule (cross-contract, zero kit code)."

echo
echo "== build the sugar CLI =="
if [ "${JAVA_FORALL_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  # GitHub restores target dirs after checkout; force this showcase to use the
  # verifier from the current source tree, not a stale cached sugar binary. In
  # CI, use an isolated target dir outside the restored workspace target cache.
  CARGO_TARGET_DIR="$TARGET_DIR" cargo clean --manifest-path "$RUST/Cargo.toml" \
    -p sugar-verifier -p sugar-cli >/dev/null 2>&1 || true
  CARGO_TARGET_DIR="$TARGET_DIR" cargo build --manifest-path "$RUST/Cargo.toml" \
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
  # Clean old state
  for p in "$HERE/$suite"/blake3-512:*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print($2)" "$1"; }

dump_consistency_rows() {
  python3 - "$1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for r in d.get("rows", []):
    prop = r.get("property", "")
    if not prop.startswith("consistency:"):
        continue
    print(f"   row {prop} status={r.get('status')}")
    reason = r.get("reason")
    if reason:
        print(f"      reason={reason}")
PY
}

dump_contract_members() {
  local dir="$1"
  python3 - "$SUGAR" "$dir" <<'PY'
import glob, json, subprocess, sys

sugar, root = sys.argv[1], sys.argv[2]
proofs = sorted(glob.glob(root + "/blake3-512:*.proof"))
if not proofs:
    print("   proof dump: no top-level proof")
    raise SystemExit

for proof in proofs:
    try:
        raw = subprocess.check_output([sugar, "dump", proof, "--json"], text=True)
        doc = json.loads(raw)
    except Exception as exc:
        print(f"   proof dump failed for {proof}: {exc}")
        continue

    print(f"   proof {doc.get('cid') or proof} members={doc.get('memberCount')}")
    for cid, member in sorted((doc.get("members") or {}).items()):
        header = member.get("header") or {}
        if header.get("kind") != "contract":
            continue
        name = header.get("contractName") or header.get("name") or cid
        inv = json.dumps(header.get("inv"), sort_keys=True, separators=(",", ":"))
        print(f"   contract {name}")
        print("      inv=" + inv[:4000])
PY
}

dump_ambient_debug() {
  local dir="$1"
  local debug_log="$dir/.prove.debug.log"
  ( cd "$dir" && RUST_LOG=debug "$SUGAR" prove . --json >/dev/null 2>"$debug_log" ) || true
  python3 - "$debug_log" <<'PY'
import sys

path = sys.argv[1]
try:
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
except FileNotFoundError:
    print("   ambient debug: missing log")
    raise SystemExit

shown = 0
for line in lines:
    if "verifier/ambient" in line:
        print("   " + line)
        shown += 1
if shown == 0:
    print("   ambient debug: no verifier/ambient lines")
PY
}

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift Java test assertions --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512:*.proof; do [ -e "$p" ] && have_proof=1; done
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
      dump_consistency_rows "$prove_json"
      echo "FAIL[$suite]: expected consistency discharge, got: $consistency_status"
      exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      dump_consistency_rows "$prove_json"
      echo "FAIL[$suite]: no consistency rows found"
      exit 1
    fi
  else
    if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
      dump_consistency_rows "$prove_json"
      dump_contract_members "$dir"
      dump_ambient_debug "$dir"
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
echo "== java-forall-loop showcase: PASS =="
