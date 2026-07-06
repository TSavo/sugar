#!/usr/bin/env bash
# Rust test-assertion consistency receipt:
#   good/ lifts one scalar #[test] assertion into an inv-only contract that is SAT.
#   bad/ lifts contradictory scalar assertions into one inv-only contract that is UNSAT.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

echo "== resolve the CLI + rust test-assertion lifter via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
"$REPO/bin/sugarbin" --profile debug --bin rust_test_assertions_rpc >/dev/null
"$REPO/bin/sugarbin" --profile debug --bin sugar-ir-smt-lib >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }

for suite in good bad; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/target" 2>/dev/null || true
done

consistency_statuses() {
  python3 - "$REPO" "$1" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

d = load_receipt(sys.argv[2])
rows = []
for row in d.get("rows", []):
    prop = row.get("property") or ""
    if not prop.startswith("consistency:"):
        continue
    if prop.startswith("consistency:rust-source::"):
        continue
    if "witness-package" in prop:
        continue
    rows.append(row)

for row in rows:
    print(f"{row.get('status') or 'MISSING'}\t{row.get('property') or 'MISSING'}\t{row.get('reason') or ''}")
PY
}

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

  # Select all TEST-ASSERTION consistency rows, not the production function's own
  # `consistency:rust-source::<fn>` value self-contract (a single-fact inv that
  # is trivially SAT and always discharges). The SourceOracle audit (PR #2138)
  # began emitting that production self-contract into the same consistency
  # report; this receipt is about the TEST's assertion-set consistency rows,
  # whose callsites carry the test source path (`src/lib.rs::...`), NOT the
  # `rust-source::` production prefix. Check the full set so a stale first
  # discharged row cannot hide a later contradictory unsatisfied row.
  local rows
  rows="$(consistency_statuses "$prove_json")"
  if [ -z "$rows" ]; then
    echo "FAIL[$suite]: no consistency row found"
    exit 1
  fi
  echo "   consistency rows:"
  printf '%s\n' "$rows" | sed 's/^/     /'

  if [ "$expect" = "DISCHARGE" ]; then
    if printf '%s\n' "$rows" | awk -F '\t' '$1 != "discharged" { found=1 } END { exit found ? 0 : 1 }'; then
      echo "FAIL[$suite]: expected all relevant consistency rows DISCHARGED"
      exit 1
    fi
    echo "OK[$suite]: scalar assertion consistency is PROVEN."
  else
    if ! printf '%s\n' "$rows" | awk -F '\t' '$1 == "unsatisfied" { found=1 } END { exit found ? 0 : 1 }'; then
      echo "FAIL[$suite]: contradictory assertions must include an UNSATISFIED consistency row"
      exit 1
    fi
    echo "OK[$suite]: contradictory scalar assertions are REFUSED."
  fi
}

run_suite good DISCHARGE
run_suite bad REFUSE

echo
echo "==================== SELF-CHECK PASSED ===================="
echo "good/ : SAT assertion invariant -> discharged consistency row."
echo "bad/  : UNSAT assertion invariant -> refused consistency row."
