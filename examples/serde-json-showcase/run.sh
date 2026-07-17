#!/usr/bin/env bash
# serde_json showcase: real serde_json vendor rows lifted as Rust assertion
# consistency contracts and witnessed by re-running cargo test.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

echo "SCOPE: serde_json 1.0.150 exact vendor rows from tests/test.rs."
echo "SCOPE: GOOD claims are point-wise exact serialization rows; BAD is a contradiction twin."
echo "SCOPE: current discharge law refuses singleton/ambient testimony (consistency rows); load replay must stay clean."
echo "SCOPE: the witness-package axis is orthogonal to consistency -- it settles purely on cargo test pass/fail (mirrors python discharge_from_proof), so GOOD's genuinely-passing suite discharges its witness even while its consistency rows refuse."
echo "SCOPE: residuals = helper-loop structure, format-macro debug rows, cfg-dependent map ordering rows, and nonfinite-float rows."

echo "== resolve the CLI, component planners, Rust assertion lifter, and cargo-test witness lifter via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
for b in sugar-ir-smt-lib sugar-ir-lean sugar-ir-coq sugar-ir-maude sugar-walk-rpc rust_test_assertions_rpc witness_rpc discharge_cli; do
  "$REPO/bin/sugarbin" --profile debug --bin "$b" >/dev/null
done

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-smt-lib" ] || { echo "FAIL: sugar-ir-smt-lib not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-lean" ] || { echo "FAIL: sugar-ir-lean not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-coq" ] || { echo "FAIL: sugar-ir-coq not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-maude" ] || { echo "FAIL: sugar-ir-maude not built"; exit 1; }
[ -x "$BIN_DIR/sugar-walk-rpc" ] || { echo "FAIL: sugar-walk-rpc not built"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }
[ -x "$BIN_DIR/witness_rpc" ] || { echo "FAIL: witness_rpc not built"; exit 1; }
[ -x "$BIN_DIR/discharge_cli" ] || { echo "FAIL: discharge_cli not built"; exit 1; }

for suite in good bad; do
  for surface in rust-cargo-test-witness rust-test-assertions; do
    mfin="$HERE/$suite/.sugar/lift/$surface/manifest.toml.in"
    mf="$HERE/$suite/.sugar/lift/$surface/manifest.toml"
    sed "s#@BIN_DIR@#$BIN_DIR#g" "$mfin" > "$mf"
  done
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/.sugar/witnesses" "$HERE/$suite/target" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

write_component_manifest() {
  local name="$1" command="$2"
  local dir="$HERE/.sugar/components/$name"
  mkdir -p "$dir"
  cat > "$dir/manifest.toml" <<TOML
name = "$name"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = ["$command"]
TOML
}

write_component_registry() {
  rm -rf "$HERE/.sugar/components"
  write_component_manifest "rust-test-assertions" "$BIN_DIR/rust_test_assertions_rpc"
  write_component_manifest "rust-cargo-test-witness" "$BIN_DIR/witness_rpc"
  write_component_manifest "ir-compiler-smt-lib" "$BIN_DIR/sugar-ir-smt-lib"
  write_component_manifest "ir-compiler-lean" "$BIN_DIR/sugar-ir-lean"
  write_component_manifest "ir-compiler-coq" "$BIN_DIR/sugar-ir-coq"
  write_component_manifest "ir-compiler-maude" "$BIN_DIR/sugar-ir-maude"
}

write_lying_discharge() {
  local script="$1"
  cat > "$script" <<'SH'
#!/usr/bin/env sh
echo '{"verdict":"DISCHARGED","reason":"lying discharge regression"}'
SH
  chmod +x "$script"
}

write_component_registry

check_load_clean() {
  local suite="$1" phase="$2" receipt="$3"
  [ -s "$receipt" ] || { echo "FAIL[$suite]: $phase produced an empty JSON receipt"; exit 1; }
  python3 - "$suite" "$phase" "$receipt" <<'PY'
import json
import sys

suite, phase, path = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
load_errors = receipt.get("loadErrors") or []
rule2 = [
    error
    for error in load_errors
    if "rule-2" in json.dumps(error, sort_keys=True).lower()
    or "rule2" in json.dumps(error, sort_keys=True).lower()
]
if load_errors:
    raise SystemExit(
        f"FAIL[{suite}]: {phase} loadErrors={len(load_errors)} rule2={len(rule2)}"
    )
print(f"   {phase} load replay: loadErrors=0 rule2=0")
PY
}

run_suite() {
  local suite="$1" expect_consistency="$2" expect_witness="$3"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift Rust assertions and cargo-test witness package --"
  mkdir -p "$dir/.sugar/runs"
  ( cd "$dir" && SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" mint --out .sugar/runs ) >/dev/null

  local have_proof=0
  for p in "$dir"/.sugar/runs/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  echo "-- prove: consistency rows plus witness-package row --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" prove . --json ) > "$prove_json" 2>/dev/null || true
  check_load_clean "$suite" "prove" "$prove_json"

  local consistency_status witness_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:') and 'witness-package' not in (r.get('property', '') or '')]) or 'MISSING'
")"
  witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
  echo "   consistency statuses: $consistency_status"
  echo "   witness-package status: $witness_status"

  case "$expect_consistency" in
    DISCHARGE)
      if [ "$consistency_status" = "MISSING" ] || grep -vq "discharged" <<<"${consistency_status//,/$'\n'}"; then
        echo "FAIL[$suite]: expected all consistency rows discharged, got $consistency_status"
        exit 1
      fi
      ;;
    REFUSE)
      if [ "$consistency_status" = "MISSING" ]; then
        echo "FAIL[$suite]: no consistency row found"
        exit 1
      fi
      if grep -q "discharged" <<<"$consistency_status"; then
        echo "FAIL[$suite]: expected refused-not-green consistency rows, got $consistency_status"
        exit 1
      fi
      if ! grep -q "refused" <<<"$consistency_status"; then
        echo "FAIL[$suite]: expected at least one refused consistency row, got $consistency_status"
        exit 1
      fi
      ;;
    UNSAT)
      if [ "$consistency_status" = "MISSING" ]; then
        echo "FAIL[$suite]: no consistency row found"
        exit 1
      fi
      if ! grep -q "unsatisfied" <<<"$consistency_status"; then
        echo "FAIL[$suite]: expected a contradictory consistency row, got $consistency_status"
        exit 1
      fi
      ;;
    *)
      echo "FAIL[$suite]: unknown consistency expectation $expect_consistency"
      exit 1
      ;;
  esac

  if [ "$expect_witness" = "DISCHARGE" ]; then
    [ "$witness_status" = "discharged" ] || { echo "FAIL[$suite]: expected witness discharge, got $witness_status"; exit 1; }
  else
    # #3754: failing cargo-test packages settle as unsatisfied from package
    # body outcomes (never discharged). A green discharge here is the
    # witness-refusal-expected-got-discharged drift the gate classifies.
    if [ "$witness_status" = "discharged" ] || [ "$witness_status" = "MISSING" ]; then
      echo "FAIL[$suite]: expected witness refusal, got $witness_status"
      exit 1
    fi
    if [ "$witness_status" != "unsatisfied" ] && [ "$witness_status" != "refused" ]; then
      echo "FAIL[$suite]: expected witness unsatisfied/refused (not-green), got $witness_status"
      exit 1
    fi
    echo "-- prove (LYING DISCHARGE): stdout says DISCHARGED; witness row must stay not-green --"
    local lie="$dir/.sugar/lying-discharge.sh"
    write_lying_discharge "$lie"
    local lie_json="$dir/.prove_lie.json"
    ( cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" SUGAR_WITNESS_DISCHARGE_CARGO_TEST="$lie" "$SUGAR" prove . --json ) > "$lie_json" 2>/dev/null || true
    [ -s "$lie_json" ] || { echo "FAIL[$suite]: lying-discharge prove produced an empty JSON receipt"; exit 1; }
    local lie_status
    lie_status="$(pyget "$lie_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
    echo "   lying-discharge witness-package status: $lie_status"
    if [ "$lie_status" = "discharged" ]; then
      echo "FAIL[$suite]: lying discharge stdout flipped a failing witness package"
      exit 1
    fi
  fi

  echo "-- verify durable artifact --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" verify --project . --json ) > "$verify_json" 2>/dev/null || true
  python3 - "$suite" "$expect_consistency" "$expect_witness" "$verify_json" <<'PY'
import json
import sys

suite, expect_consistency, expect_witness, path = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
load_errors = receipt.get("loadErrors") or []
rule2 = [
    error
    for error in load_errors
    if "rule-2" in json.dumps(error, sort_keys=True).lower()
    or "rule2" in json.dumps(error, sort_keys=True).lower()
]
if load_errors:
    raise SystemExit(
        f"FAIL[{suite}]: durable verify loadErrors={len(load_errors)} rule2={len(rule2)}"
    )
rows = receipt.get("rows", [])
consistency = [
    r.get("status")
    for r in rows
    if (r.get("property") or "").startswith("consistency:")
    and "witness-package" not in (r.get("property") or "")
]
witness = [
    r.get("status")
    for r in rows
    if "witness-package" in (r.get("property") or "")
]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect_consistency == "DISCHARGE":
    if any(status != "discharged" for status in consistency):
        raise SystemExit(f"FAIL[{suite}]: durable consistency statuses {consistency}")
elif expect_consistency == "REFUSE":
    if any(status == "discharged" for status in consistency) or "refused" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: durable consistency statuses {consistency}")
elif expect_consistency == "UNSAT":
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: durable consistency statuses {consistency}")
else:
    raise SystemExit(f"FAIL[{suite}]: unknown consistency expectation {expect_consistency}")
if expect_witness == "DISCHARGE":
    if witness != ["discharged"]:
        raise SystemExit(f"FAIL[{suite}]: durable witness statuses {witness}")
else:
    if witness == ["discharged"] or not witness:
        raise SystemExit(f"FAIL[{suite}]: durable witness statuses {witness}")
verified = any(
    w.get("verdict") == "verified"
    for w in receipt.get("witnessDimension", {}).get("witnesses", [])
)
if not verified:
    raise SystemExit(f"FAIL[{suite}]: witness dimension did not verify")
print(f"   durable consistency statuses: {','.join(consistency)}")
print(f"   durable witness statuses: {','.join(witness)}")
print("   durable load replay: loadErrors=0 rule2=0")
print("   durable witness dimension: verified")
PY
}

run_suite good REFUSE DISCHARGE
run_suite bad UNSAT REFUSE

echo
echo "==================== SELF-CHECK PASSED ===================="
echo "good/ : serde_json exact vendor rows load clean and refuse-not-green under current discharge law."
echo "bad/  : contradictory serde_json row refuses in consistency and witness axes."
