#!/usr/bin/env bash
# regex showcase: real regex vendor rows lifted as Rust assertion consistency
# contracts and witnessed by re-running cargo test.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"

echo "SCOPE: regex 1.12.4 exact vendor rows from tests/regression.rs and tests/regression_fuzz.rs."
echo "SCOPE: GOOD claims are point-wise exact compile/is_match rows; BAD is a contradiction twin."
echo "SCOPE: residuals = data-driven TOML suite, iterator collection rows, capture indexing, replacement macro rows, ignored fuzz rows, and feature-gated Unicode variants."

echo "== build the CLI + Rust assertion and cargo-test witness lifters =="
cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-cli --bin sugar \
  -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
  -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
  -p sugar-lift-rust-cargo-test-witness --bin discharge_cli >/dev/null

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

# Consistency rows now split honestly (PR #3691): a lone ground
# `str.in-regex(subject, R)` reaches z3's regex-as-language universe and
# genuinely DISCHARGES (matching subject) or is genuinely UNSATISFIED
# (contradiction twin, non-matching subject) -- the covering-universe path.
# A lone PLAIN-EUF row with no sibling and no covering universe stays
# honestly vacuous-REFUSED, named by the exact vacuity reason string. Never
# suppress a row's terminal state: assert every row is one of these three
# shapes, by name, or fail loudly on an unnamed status.
check_consistency_rows() {
  local path="$1" expect="$2" suite="$3"
  python3 - "$path" "$expect" "$suite" <<'PY'
import json
import sys

path, expect, suite = sys.argv[1:4]
receipt = json.load(open(path, encoding="utf-8"))
rows = [
    r
    for r in receipt.get("rows", [])
    if (r.get("property") or "").startswith("consistency:")
    and "witness-package" not in (r.get("property") or "")
]
if not rows:
    print(f"FAIL[{suite}]: no consistency row found")
    sys.exit(1)

VACUOUS_REASON = "no covering universe joins the left-operand term"
discharged = [r for r in rows if r.get("status") == "discharged"]
unsatisfied = [r for r in rows if r.get("status") == "unsatisfied"]
vacuous = [
    r
    for r in rows
    if r.get("status") == "refused" and VACUOUS_REASON in (r.get("reason") or "")
]
named = discharged + unsatisfied + vacuous
unnamed = [r for r in rows if r not in named]
if unnamed:
    shapes = ", ".join(
        f"{r.get('property')}={r.get('status')}:{r.get('reason')}" for r in unnamed
    )
    print(f"FAIL[{suite}]: unnamed consistency terminal state(s): {shapes}")
    sys.exit(1)

if expect == "DISCHARGE":
    if unsatisfied:
        props = ", ".join(r.get("property") for r in unsatisfied)
        print(f"FAIL[{suite}]: expected no contradictions, got unsatisfied row(s): {props}")
        sys.exit(1)
    if not discharged:
        print(f"FAIL[{suite}]: expected at least one genuinely discharged membership row, got none")
        sys.exit(1)
else:
    if not unsatisfied:
        print(f"FAIL[{suite}]: expected a contradictory (unsatisfied) consistency row, got none")
        sys.exit(1)

print(
    f"   consistency[{suite}]: {len(discharged)} discharged, "
    f"{len(vacuous)} honestly vacuous-refused (named), {len(unsatisfied)} unsatisfied"
)
PY
}

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

  local witness_status
  witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
  echo "   witness-package status: $witness_status"

  check_consistency_rows "$prove_json" "$expect_consistency" "$suite"

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
  check_consistency_rows "$verify_json" "$expect_consistency" "$suite (durable)"
  python3 - "$suite" "$expect_witness" "$verify_json" <<'PY'
import json
import sys

suite, expect_witness, path = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
witness = [
    r.get("status")
    for r in rows
    if "witness-package" in (r.get("property") or "")
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
print(f"   durable witness statuses: {','.join(witness)}")
print("   durable witness dimension: verified")
PY
}

run_suite good DISCHARGE DISCHARGE
run_suite bad REFUSE REFUSE

echo
echo "==================== SELF-CHECK PASSED ===================="
echo "good/ : regex exact vendor rows genuinely discharge (membership covering-universe, PR #3691);"
echo "        any plain-EUF lone row stays honestly vacuous-refused, named by reason; witness package verifies."
echo "bad/  : contradictory regex row is genuinely unsatisfied in consistency; witness axis refuses too."
