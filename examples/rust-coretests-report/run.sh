#!/usr/bin/env bash
# Honest coverage ledger for the Rust assertion-lift kit over the Rust stdlib
# `coretests` corpus (vendored under ./corpus/tests). This is the MEASURING STICK:
# it runs `sugar lift --report` over every coretests file and prints the source
# audit -- how many assertion loci are `warranted` (lifted to a FOL fact) vs
# `unresolved` (no sugar yet -- the visible dark) vs `support` (INERT source only:
# comments, doc-comments, compiler pragmas). `support` is NOT a place to hide
# "we don't have sugar for that yet"; that is `unresolved`, and progress is
# measured by driving it down with real Sugar.
#
# Usage: ./run.sh            # full corpus
#        SUBDIR=iter ./run.sh  # restrict to corpus/tests/<SUBDIR> (faster)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
# RELEASE only -- never run a debug build against a large corpus (the lifter is
# spawned per file; debug is an order of magnitude slower).
BIN_DIR="$RUST/target/release"
SUGAR="$BIN_DIR/sugar"
CORPUS="$HERE/corpus"

echo "== build the CLI + the Rust assertion lifter (release) =="
cargo build --release --manifest-path "$RUST/Cargo.toml" \
  -p sugar-cli --bin sugar \
  -p sugar-lift-rust-tests --bin rust_test_assertions_rpc >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }

# Render the lift manifest with this checkout's binary path (portable: the
# checked-in template carries @BIN_DIR@, never an absolute path).
mfin="$CORPUS/.sugar/lift/rust-test-assertions/manifest.toml.in"
mf="$CORPUS/.sugar/lift/rust-test-assertions/manifest.toml"
sed "s#@BIN_DIR@#$BIN_DIR#g" "$mfin" > "$mf"

OUT="$HERE/coretests-report.json"
echo "== lift --report over $(fd -e rs . "$CORPUS/tests" 2>/dev/null | wc -l | tr -d ' ') coretests files =="
( cd "$CORPUS" && "$SUGAR" lift --report --json ) > "$OUT" 2>"$HERE/coretests-report.err" || true

echo "== honest source ledger =="
# Print the headline accounting lines the human report emits.
( cd "$CORPUS" && "$SUGAR" lift --report 2>/dev/null ) \
  | grep -E "source audit:|assertion surface accounting:" || {
    echo "(no headline accounting emitted; see $HERE/coretests-report.err)"; exit 1;
  }
echo
echo "full JSON ledger: $OUT"
echo "NOTE: 'unresolved' is the honest dark (no sugar yet). 'support' is inert source ONLY."
