#!/usr/bin/env bash
# run-rust-universe-e2e.sh: the IDE PROVE-path receipt for the rust CASE 2
# squiggle (#3774) -- vendor UNIVERSE + vendor fact projected at the
# consumer's own argument.
#
# Sibling of run-rust-prove-e2e.sh (case 1: stated-vs-stated); this drives the
# SAME `proveClient.proveProject` code over
# examples/rust-forall-universe-federation (a rust vendor whose ONLY testimony
# is a lifted bounded-loop forall universe) and asserts:
#
#   consumer-bad  (block_width(3) == 128) -> RED diagnostic @ the assert line,
#                 squiggle carries Vendor fact / Vendor universe / Your fact
#                 -> UNSAT
#   consumer-good (block_width(5) == 64)  -> no diagnostic; the row is
#                 DISCHARGED by the universe (independent-KIND witness)
#   flip the literal both ways -> the diagnostic appears / clears.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$EXT_DIR/../.." && pwd)"

echo "== resolve sugar + rust lifters via sugarbin =="
SUGAR_BIN="$("$REPO/bin/sugarbin" --profile release)"
export SUGAR_BIN
echo "   $SUGAR_BIN"
for b in rust_test_assertions_rpc witness_rpc discharge_cli sugar-ir-smt-lib sugar-walk-rpc; do
  "$REPO/bin/sugarbin" --profile release --bin "$b" >/dev/null
done
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required"; exit 1; }

export SUGAR_EXAMPLE_DIR="$REPO/examples/rust-forall-universe-federation"

echo "== compile the TypeScript client =="
cd "$EXT_DIR"
if [ ! -d node_modules ]; then
  npm install --silent
fi
npm run --silent compile

echo "== run the headless RUST UNIVERSE red -> green -> red receipt =="
node ./test/rust-universe-e2e.test.js
