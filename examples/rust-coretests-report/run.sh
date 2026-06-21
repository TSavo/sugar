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
  -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
  -p sugar-lift-rust-tests --bin discharge_sweep >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }

# Render the lift manifest with this checkout's binary path (portable: the
# checked-in template carries @BIN_DIR@, never an absolute path).
mfin="$CORPUS/.sugar/lift/rust-test-assertions/manifest.toml.in"
mf="$CORPUS/.sugar/lift/rust-test-assertions/manifest.toml"
sed "s#@BIN_DIR@#$BIN_DIR#g" "$mfin" > "$mf"

OUT="$HERE/coretests-report.out"
ERR="$HERE/coretests-report.err"
echo "== lift --report over $(fd -e rs . "$CORPUS/tests" 2>/dev/null | wc -l | tr -d ' ') coretests files =="
# ONE lift (not two): stdout carries the human ledger, stderr carries the factory
# disposition trace we tally below into the target list. Disable ANSI at the source
# (the lifter's tracing layer emits color escapes even when stderr is redirected to a
# file) -- belt-and-suspenders with the strip below.
( cd "$CORPUS" && NO_COLOR=1 RUST_LOG_STYLE=never CLICOLOR=0 TERM=dumb "$SUGAR" lift --report ) > "$OUT" 2>"$ERR" || true

# ANSI-strip BOTH streams before parsing. The lifter writes color escapes into the
# trace; those escapes sit between/inside the `selected="..."` tokens and silently break
# the grep below -- 0 matches reads as an EMPTY target histogram, which looks like "no
# dark" when it is really a parsing failure. Never parse the raw colored stream. (BSD/macOS
# sed has no \x1b, so the ESC byte is injected via bash $'...' ANSI-C quoting.)
OUTP="$HERE/coretests-report.plain.out"
ERRP="$HERE/coretests-report.plain.err"
sed $'s/\x1b\\[[0-9;]*m//g' "$OUT" > "$OUTP"
sed $'s/\x1b\\[[0-9;]*m//g' "$ERR" > "$ERRP"

echo
echo "== honest source ledger =="
grep -E "source audit:|assertion surface accounting:" "$OUTP" || {
  # INSTRUMENT-NEVER-DARK: no headline means the measurement FAILED -- surface the loud
  # named reason (the CLI now hard-errors naming an upstream byte-bound refusal) and exit
  # non-zero. A blind ledger that prints nothing must never read as "clean".
  echo "MEASUREMENT FAILED: no source-audit headline emitted. Cause (stderr tail):"
  tail -5 "$ERRP"
  exit 1
}

echo
echo "== missing-sugar target list (unresolved, by the sugar that hit its backstop) =="
echo "   'no sugar yet' for these shapes -- the honest dark to drive to zero. Top 20:"
rg -o 'selected="[^"]+" disposition="unresolved"' "$ERRP" 2>/dev/null \
  | sed -E 's/selected="([^"]+)".*/\1/' | sort | uniq -c | sort -rn | head -20 \
  | sed 's/^/     /' || echo "     (none)"

echo
echo "== deliberate refusals (NOT targets -- sound effects/vacuity/mut-ref guards) =="
rg -o 'selected="[^"]+" disposition="refused"' "$ERRP" 2>/dev/null \
  | sed -E 's/selected="([^"]+)".*/\1/' | sort | uniq -c | sort -rn | head -10 \
  | sed 's/^/     /' || echo "     (none)"

echo
echo "stdout ledger: $OUT   |   disposition trace: $ERR   (ANSI-stripped: $OUTP / $ERRP)"
echo "NOTE: 'unresolved' is the honest dark (no sugar yet). 'support' is inert source ONLY (kit-marked)."

# ── TEETHED LEDGER (the proof dial, not just coverage) ───────────────────────
# The ledger above measures COVERAGE: how many loci `warranted` = lifted to a
# checkable FOL fact (NO solver runs at lift). That cannot tell a teethed
# obligation (a wrong value would refute it) from a congruence-only / opaque one
# (SAT for any value -- no teeth). This SECOND, additive pass runs the verifier's
# DISCHARGE GATE (negation-UNSAT) over every warranted obligation and reports the
# real proof split: DISCHARGED (proven), REFUTED (proven false), UNDECIDED (the
# no-teeth bucket coverage hid -- distinct from 'unresolved' = not-lifted-at-all).
echo
echo "== teethed ledger (discharge gate -- proof, not just coverage) =="
TEETH_JSON="$HERE/coretests-teethed.json"
if [ -x "$BIN_DIR/discharge_sweep" ]; then
  "$BIN_DIR/discharge_sweep" "$CORPUS" --json "$TEETH_JSON" || {
    echo "(discharge sweep did not complete; see above)"; }
  echo "teethed ledger json: $TEETH_JSON"
else
  echo "(discharge_sweep not built -- skipping the proof dial)"
fi
