#!/usr/bin/env bash
# self-accounting.sh — recompute sugar's total-accounting over its OWN source,
# with NO oracle and NO trust.
#
# This is the "handed to a stranger who recomputes it" artifact for the
# accounting half of the GOAL (docs/self-application/GOAL-sugar-proves-sugar.md).
# It does not ask you to trust a verdict; it RECOMPUTES the verdict from your
# checkout. The load-bearing invariant is the one the whole product rests on:
# silent = 0, structurally.
#
#   Rust   — coretests_sweep over each sugar crate's src/: every assert* macro is
#            lifted to FOL or refused by name; genuinely-unreached (silent) = 0.
#
# Python's value-pin scan (scan_module_value_pins) had no production caller and
# was deleted (#7757).
#
# Java is intentionally absent: sugar's live Java is a 3-file lifter kit with no
# Java-assert self-test corpus (see the ledger's Java section) — there is nothing
# of sugar's own Java to self-account. Naming that absence is the honest move.
#
# Exit non-zero iff silent != 0 anywhere (the gate a stranger can fail).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

RUST_CRATES=(libsugar sugar-ir-compiler-smt-lib sugar-cli sugar-verifier sugar-walk)
fail=0

echo "==================================================================="
echo " sugar self-accounting — recompute, do not trust"
echo " repo: $REPO"
echo "==================================================================="

# ---- Rust: assertion-lift axis -------------------------------------------------
echo
echo "## Rust (assertion-lift axis: coretests_sweep)"
SWEEP="implementations/rust/target/debug/coretests_sweep"
# ALWAYS build from current source — a recomputable artifact must reflect the
# checkout, never a stale binary. cargo is incremental, so this is a no-op when
# already fresh.
echo "-- building coretests_sweep from current source --"
cargo build --manifest-path implementations/rust/Cargo.toml \
  -p sugar-lift-rust-tests --bin coretests_sweep >/dev/null 2>&1

r_assert=0; r_lift=0; r_ref=0; r_silent=0
for c in "${RUST_CRATES[@]}"; do
  out="$("$SWEEP" "implementations/rust/$c/src" 2>/dev/null)"
  a=$(echo "$out" | rg -o "assertion macros seen: \d+" | rg -o "\d+")
  d=$(echo "$out" | rg -o "discharged \(lifted to FOL\): +\d+" | rg -o "\d+$")
  rf=$(echo "$out" | rg -o "refused +\(TERMINAL[^:]*: +\d+" | rg -o "\d+$")
  s=$(echo "$out" | rg -o "missing assertions \(SILENT\): +\d+" | rg -o "\d+$" | head -1)
  printf "   %-28s asserts=%-5s lifted=%-5s refused=%-4s SILENT=%s\n" "$c" "$a" "$d" "$rf" "$s"
  r_assert=$((r_assert+a)); r_lift=$((r_lift+d)); r_ref=$((r_ref+rf)); r_silent=$((r_silent+s))
done
echo "   ----"
printf "   TOTAL  asserts=%s lifted=%s refused=%s SILENT=%s\n" "$r_assert" "$r_lift" "$r_ref" "$r_silent"
[ "$r_silent" = "0" ] || { echo "   FAIL: Rust silent != 0"; fail=1; }

echo
echo "==================================================================="
if [ "$fail" = "0" ]; then
  echo " RESULT: silent = 0. Accounting is total."
  echo " (Recompute this yourself; the verdict is falsifiable, not trusted.)"
else
  echo " RESULT: FAIL — a silent drop was found. The accounting is NOT total."
fi
echo "==================================================================="
exit "$fail"
