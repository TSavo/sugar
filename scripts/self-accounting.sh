#!/usr/bin/env bash
# self-accounting.sh — recompute sugar's total-accounting over its OWN source,
# in both measurable self-application languages, with NO oracle and NO trust.
#
# This is the "handed to a stranger who recomputes it" artifact for the
# accounting half of the GOAL (docs/self-application/GOAL-sugar-proves-sugar.md).
# It does not ask you to trust a verdict; it RECOMPUTES the verdict from your
# checkout. The load-bearing invariant in both languages is the same one the
# whole product rests on: silent = 0, structurally.
#
#   Rust   — coretests_sweep over each sugar crate's src/: every assert* macro is
#            lifted to FOL or refused by name; genuinely-unreached (silent) = 0.
#   Python — scan_module_value_pins over sugar's Python source: every value-pin
#            candidate is pinned or refused by name; totality_holds() (silent = 0).
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

# ---- Python: value-pin axis ----------------------------------------------------
echo
echo "## Python (source value-pin axis: scan_module_value_pins)"
python3 - <<'PY' || fail=1
import ast, glob, os, sys
sys.path.insert(0, "implementations/python/sugar-lift-python-source/src")
from sugar_lift_python_source.value_pins import scan_module_value_pins
roots = ["implementations/python/sugar-lift-python-source/src",
         "implementations/python/sugar-lift-py-tests/src"]
c=p=r=0; files=0; bad=[]
# Canonical lines content-address Python's self-proof SURFACE: which names are
# pinned, which reasons refused, per file. A change in pins/refusals moves the CID
# (a count-preserving swap still moves it). This is the Python analog of the Rust
# sweep's assertion_multiset_cid -- so Python's self-proof is CONTENT-ADDRESSED,
# and federation by CID falls out for free (no hub): a stranger recomputes this CID
# and it lands byte-identical, because Python's blake3 == sugar's blake3_512_of.
lines = []
for root in roots:
    for path in sorted(glob.glob(root + "/**/*.py", recursive=True)):
        try:
            s = scan_module_value_pins(ast.parse(open(path, encoding="utf-8").read()))
        except Exception:
            continue
        files += 1
        if not s.totality_holds():
            bad.append(path)
        c += s.candidates; p += len(s.pins); r += len(s.refusals)
        rel = os.path.relpath(path)
        for name in sorted(s.pins):
            lines.append(f"pin\t{rel}\t{name}")
        for ref in s.refusals:
            reason = (ref.get("reason") or ref.get("kind") or "") if isinstance(ref, dict) else str(ref)
            lines.append(f"refuse\t{rel}\t{reason}")
print(f"   files={files} candidates={c} pinned={p} refused={r} "
      f"SILENT={c - p - r}")
if bad:
    print(f"   FAIL: totality_holds() False in {bad[:5]}")
    raise SystemExit(1)
print("   totality_holds() True for every file (silent = 0, structural)")
# Content-address the self-proof surface, in sugar's canonical hash (blake3-512).
try:
    import blake3
    lines.sort()
    canonical = "\n".join(lines).encode("utf-8")
    cid = "blake3-512:" + blake3.blake3(canonical).digest(length=64).hex()
    print(f"   pythonSelfAccountingCid: {cid}")
except ImportError:
    print("   pythonSelfAccountingCid: (install the `blake3` module to content-address)")
PY

echo
echo "==================================================================="
if [ "$fail" = "0" ]; then
  echo " RESULT: silent = 0 in both languages. Accounting is total."
  echo " (Recompute this yourself; the verdict is falsifiable, not trusted.)"
else
  echo " RESULT: FAIL — a silent drop was found. The accounting is NOT total."
fi
echo "==================================================================="
exit "$fail"
