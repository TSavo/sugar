#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUST_DIR="$ROOT/implementations/rust"
OUT_DIR="$ROOT/examples/forall-vampire-showcase/.generated"
PROJECT="$OUT_DIR/project"
VERIFY_JSON="$OUT_DIR/.verify.json"
Z3_SMT="$OUT_DIR/z3-good-obligation.smt2"
Z3_OUT="$OUT_DIR/.z3.out"

mkdir -p "$OUT_DIR"

for bin in z3 python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "missing required binary: $bin" >&2
    exit 2
  fi
done
if ! command -v vampire >/dev/null 2>&1; then
  echo "SKIP: vampire not installed on this runner; forall-vampire showcase needs a first-order prover. Skipping (gated where vampire is present)." >&2
  exit 0
fi

cd "$RUST_DIR"
cargo run -q -p sugar-cli --example forall_vampire_fixture -- "$PROJECT" >/dev/null

cat > "$Z3_SMT" <<'SMT'
(set-logic ALL)
(declare-fun mul (Int Int) Int)
(declare-fun inv (Int) Int)
(declare-fun e () Int)
(assert (not
  (=>
    (and
      (forall ((x Int) (y Int) (z Int))
        (= (mul (mul x y) z) (mul x (mul y z))))
      (forall ((x Int)) (= (mul e x) x))
      (forall ((x Int)) (= (mul (inv x) x) e)))
    (forall ((x Int)) (= (mul x e) x)))))
(check-sat)
SMT

z3_rc=0
timeout 10 z3 -smt2 "$Z3_SMT" > "$Z3_OUT" 2>&1 || z3_rc=$?

SUGAR="$("$ROOT/bin/sugarbin" --profile release)"
verify_rc=0
(
  cd "$PROJECT"
  "$SUGAR" verify --project . --emit-witnesses "$PROJECT/witnesses-out" --json
) > "$VERIFY_JSON" || verify_rc=$?

python3 - "$ROOT" "$VERIFY_JSON" "$Z3_OUT" "$z3_rc" "$verify_rc" <<'PY'
import sys
from pathlib import Path

root, verify_path, z3_path, z3_rc, verify_rc = sys.argv[1:6]
sys.path.insert(0, root)
from tools.showcase.json_get import load_receipt

receipt = load_receipt(verify_path)
claims = {row["property"]: row for row in receipt["claims"]}
missing = [
    name
    for name in (
        "forall_vampire_good_right_identity",
        "forall_vampire_bad_false_universal",
    )
    if name not in claims
]
if missing:
    available = ", ".join(sorted(claims)) or "<none>"
    raise SystemExit(
        "FAIL: missing forall-vampire claim row(s): "
        + ", ".join(missing)
        + f"; available rows: {available}"
    )
good = claims["forall_vampire_good_right_identity"]
bad = claims["forall_vampire_bad_false_universal"]
z3_text = Path(z3_path).read_text(encoding="utf-8").strip()

print(f"z3_rc={z3_rc} z3_output={z3_text or '<empty>'}")
print(
    "GOOD "
    f"status={good['status']} "
    f"routed={good['routedSolver']} "
    f"closed_by={good['dischargingSolver']} "
    f"witness={good['witnessCid']}"
)
print(
    "BAD "
    f"status={bad['status']} "
    f"routed={bad['routedSolver']} "
    f"closed_by={bad['dischargingSolver']}"
)

if z3_rc != "124" and z3_text != "unknown":
    raise SystemExit(f"expected z3 timeout rc=124 or unknown, got rc={z3_rc} output={z3_text!r}")
if good["obligationClass"] != "first-order":
    raise SystemExit(f"GOOD wrong class: {good}")
if good["routedSolver"] != "vampire":
    raise SystemExit(f"GOOD wrong route: {good}")
if good["status"] != "discharged" or not str(good["dischargingSolver"]).startswith("vampire@"):
    raise SystemExit(f"GOOD not closed by Vampire: {good}")
if bad["obligationClass"] != "first-order":
    raise SystemExit(f"BAD wrong class: {bad}")
if bad["routedSolver"] != "vampire":
    raise SystemExit(f"BAD wrong route: {bad}")
if bad["status"] != "unsatisfied":
    raise SystemExit(f"BAD not refused as unsatisfied: {bad}")
if verify_rc != "1":
    raise SystemExit(f"expected verify rc=1 because BAD is false, got {verify_rc}")
PY

echo "verify_json=$VERIFY_JSON"
