#!/usr/bin/env bash
# run-rust-prove-e2e.sh: the IDE PROVE-path receipt for a RUST consumer
# (#3774 "the LSP with pandas and rust kit").
#
# Drives the SAME code the VS Code extension runs -- `proveClient.proveProject`
# -- which shells `sugar prove --json` on a rust consumer PROJECT and maps
# `unsatisfied` rows to diagnostics at the assertion's source locus. Uses the
# REAL fixture (examples/rust-serde-federation: a real serde_json 1.0.150
# vendor row + a rust consumer, staged .proof, NO annotations) and asserts the
# rust parity of the python flip:
#
#   consumer-bad  (assert_eq!(s, "false")) -> RED diagnostic @ the assert line
#   consumer-good (assert_eq!(s, "true"))  -> no diagnostic
#   flip the literal both ways -> the diagnostic appears / clears.
#
# The `sugar` binary and rust lifter binaries are resolved through the ONE
# published door (bin/sugarbin); no cargo is invoked directly by the extension
# path (mint shells the lift RPC binaries, not `cargo build`).
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

export SUGAR_EXAMPLE_DIR="$REPO/examples/rust-serde-federation"

echo "== compile the TypeScript client =="
cd "$EXT_DIR"
if [ ! -d node_modules ]; then
  npm install --silent
fi
npm run --silent compile

echo "== run the headless RUST PROVE-path red -> green -> red receipt =="
node ./test/rust-prove-e2e.test.js
