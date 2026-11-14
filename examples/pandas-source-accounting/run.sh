#!/usr/bin/env bash
# Full pandas package mint. The vendor fixed point is tiny on purpose: it seeds
# one local source warrant, and `sugar mint` (the one driver of the Python kit,
# step 1) walks it into a `.proof`.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"
VENV="${PANDAS_WITNESS_VENV:-/tmp/pandas-witness-venv}"

if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import pandas, blake3, cbor2, nacl
PY
then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q pandas pytest pynacl blake3 cbor2
fi

[ -x "$BIN" ] || { echo "FAIL: sugarbin returned a missing binary: $BIN"; exit 1; }

cd "$HERE/good"
rm -f blake3-512_*.proof .pandas-source-report.json .pandas-source-report.txt 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses __pycache__ 2>/dev/null || true

echo "== sugar mint (pandas package) =="
"$BIN" mint --out .

have_proof=0
for p in blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
[ "$have_proof" = 1 ] || { echo "FAIL: mint produced no .proof"; exit 1; }

echo ""
echo "==== pandas-source-accounting: PASS ===="
