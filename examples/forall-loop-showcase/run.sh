#!/usr/bin/env bash
# forall-loop showcase: a bounded loop lifted as a guarded universal
# (forall x. 0<=x<3 => g(x)==1), witnessed by re-running cargo test.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

echo "SCOPE: a concrete bounded loop lifts to forall x. (0 <= x < 3 => g(x) == 1)."
echo "SCOPE: GOOD is the universal alone (consistent); BAD adds the in-range contradiction g(2)==2 (z3 instantiates x=2 and refutes)."
echo "SCOPE: residuals = runtime-collection loops, mutated-accumulator bodies, open ranges (all sound refusals)."

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
  python3 - "$suite" "$expect_consistency" "$expect_witness" "$verify_json" <<'PY'
import json
import sys

suite, expect_consistency, expect_witness, path = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
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
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: durable consistency statuses {consistency}")
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
echo "== forall-loop showcase: PASS =="
