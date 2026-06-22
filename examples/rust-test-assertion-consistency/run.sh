#!/usr/bin/env bash
# Rust test-assertion consistency receipt:
#   good/ lifts one scalar #[test] assertion into an inv-only contract that is SAT.
#   bad/ lifts contradictory scalar assertions into one inv-only contract that is UNSAT.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"

echo "== build the CLI + rust test-assertion lifter =="
cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-cli \
  -p sugar-lift-rust-tests \
  --bins >/dev/null 2>&1 || cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-cli -p sugar-lift-rust-tests --bins

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }

for suite in good bad; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/target" 2>/dev/null || true
done

pyget() { python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print($2)" "$1"; }

run_suite() {
  local suite="$1" expect="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite (expect $expect) ===================="

  echo "-- mint: lift #[test] assertions -> inv-only .proof --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  echo "-- prove: raw SAT consistency over the lifted inv --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json ) > "$prove_json" 2>/dev/null || true

  # Select the TEST-ASSERTION consistency row, not the production function's own
  # `consistency:rust-source::<fn>` value self-contract (a single-fact inv that
  # is trivially SAT and always discharges). The SourceOracle audit (PR #2138)
  # began emitting that production self-contract into the same consistency
  # report; this receipt is about the TEST's assertion-set consistency, which is
  # the row whose callsite carries the test's source path (`src/lib.rs::...`),
  # NOT the `rust-source::` production prefix.
  local row_filter="(r.get('property','') or '').startswith('consistency:') and not (r.get('property','') or '').startswith('consistency:rust-source::') and 'witness-package' not in (r.get('property','') or '')"
  local status reason
  status="$(pyget "$prove_json" "next((r.get('status') for r in d.get('rows',[]) if $row_filter), 'MISSING')")"
  reason="$(pyget "$prove_json" "next((r.get('reason') for r in d.get('rows',[]) if $row_filter), 'MISSING')")"
  echo "   consistency row status: $status"
  echo "   reason: $reason"

  if [ "$expect" = "DISCHARGE" ]; then
    if [ "$status" != "discharged" ]; then
      echo "FAIL[$suite]: expected consistency DISCHARGED, got status=$status"
      exit 1
    fi
    echo "OK[$suite]: scalar assertion consistency is PROVEN."
  else
    if [ "$status" = "discharged" ]; then
      echo "FAIL[$suite]: contradictory assertions must REFUSE, got discharged"
      exit 1
    fi
    if [ "$status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency row found"
      exit 1
    fi
    echo "OK[$suite]: contradictory scalar assertions are REFUSED (status=$status)."
  fi
}

run_suite good DISCHARGE
run_suite bad REFUSE

echo
echo "==================== SELF-CHECK PASSED ===================="
echo "good/ : SAT assertion invariant -> discharged consistency row."
echo "bad/  : UNSAT assertion invariant -> refused consistency row."
