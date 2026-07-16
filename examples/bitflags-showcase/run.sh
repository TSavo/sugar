#!/usr/bin/env bash
# bitflags 2.6.0 showcase: real vendor rows lifted as Rust assertion
# consistency contracts and witnessed by re-running cargo test.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

echo "SCOPE: bitflags 2.6.0 exact vendor rows from bitflags tests and doc-examples."
echo "SCOPE: GOOD claims are point-wise exact contains/bits/intersection/union/is_empty rows; BAD is a contradiction twin."
echo "SCOPE: residuals = formatting rows, serde feature-gated rows, from_bits_truncate edge rows, named/unnamed flag rows."

echo "== resolve the CLI + Rust assertion and cargo-test witness lifters via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
"$REPO/bin/sugarbin" --profile debug --bin rust_test_assertions_rpc >/dev/null
"$REPO/bin/sugarbin" --profile debug --bin witness_rpc >/dev/null
"$REPO/bin/sugarbin" --profile debug --bin discharge_cli >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
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
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json "$HERE/$suite/Cargo.lock" 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

write_lying_discharge() {
  local script="$1"
  cat > "$script" <<'SH'
#!/usr/bin/env sh
echo '{"verdict":"DISCHARGED","reason":"lying discharge regression"}'
SH
  chmod +x "$script"
}

run_suite() {
  local suite="$1" expect_consistency="$2" expect_witness="$3"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift Rust assertions and cargo-test witness package --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  echo "-- prove: consistency rows plus witness-package row --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json ) > "$prove_json" 2>/dev/null || true

  local consistency_status witness_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:') and 'witness-package' not in (r.get('property', '') or '')]) or 'MISSING'
")"
  witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
  echo "   prove consistency statuses: $consistency_status"
  echo "   prove witness-package status: $witness_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    echo "$consistency_status" | grep -qv 'unsatisfied' || { echo "FAIL[$suite]: expected consistency discharge, got $consistency_status"; exit 1; }
  else
    echo "$consistency_status" | grep -q 'unsatisfied' || { echo "FAIL[$suite]: expected consistency refusal, got $consistency_status"; exit 1; }
  fi

  if [ "$expect_witness" = "DISCHARGE" ]; then
    [ "$witness_status" = "discharged" ] || { echo "FAIL[$suite]: expected witness discharge, got $witness_status"; exit 1; }
  else
    if [ "$witness_status" = "discharged" ] || [ "$witness_status" = "MISSING" ]; then
      echo "FAIL[$suite]: expected witness refusal, got $witness_status"
      exit 1
    fi
    echo "-- prove (LYING DISCHARGE): stdout says DISCHARGED, package body still has a failed outcome --"
    local lie="$dir/.sugar/lying-discharge.sh"
    write_lying_discharge "$lie"
    local lie_json="$dir/.prove_lie.json"
    ( cd "$dir" && SUGAR_WITNESS_DISCHARGE_CARGO_TEST="$lie" "$SUGAR" prove . --json ) > "$lie_json" 2>/dev/null || true
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
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json ) > "$verify_json" 2>/dev/null || true
  python3 - "$suite" "$expect_consistency" "$expect_witness" "$verify_json" "$REPO" <<'PY'
import sys

suite, expect_consistency, expect_witness, path, repo = sys.argv[1:]
sys.path.insert(0, repo)
from tools.showcase.durable_consistency import (
    check_durable_consistency,
    is_witness_package_row,
)
from tools.showcase.json_get import load_receipt

receipt = load_receipt(path)
rows = receipt.get("rows", [])
consistency = check_durable_consistency(
    rows, suite=suite, expect=expect_consistency
)
witness = [
    r.get("status")
    for r in rows
    if is_witness_package_row(r)
]
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
print("   durable witness dimension: verified")
PY
}

run_suite good DISCHARGE DISCHARGE
run_suite bad REFUSE REFUSE

echo
echo "== bitflags 2.6.0 showcase: PASS =="
