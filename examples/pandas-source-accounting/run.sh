#!/usr/bin/env bash
# Full pandas source-accounting report. The vendor fixed point is tiny on
# purpose: it seeds a source warrant into pandas.core.arrays.boolean, and the
# package-accounting pass then recursively accounts for the installed pandas
# package source as warranted/support/inactive/refused/unclassified.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$REPO/implementations/rust/target/debug/sugar"
VENV="${PANDAS_WITNESS_VENV:-/tmp/pandas-witness-venv}"

if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import pandas, blake3, cbor2, nacl
PY
then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q pandas pytest pynacl blake3 cbor2
fi

echo "== build the CLI =="
cargo build --manifest-path "$REPO/implementations/rust/Cargo.toml" -p sugar-cli --bin sugar >/dev/null

cd "$HERE/good"
rm -f blake3-512_*.proof .pandas-source-report.json .pandas-source-report.txt 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses __pycache__ 2>/dev/null || true

echo "== sugar lift --report --json (full pandas package source accounting) =="
"$BIN" lift --report --json . > .pandas-source-report.json

"$VENV/bin/python" - <<'PY'
import json
from pathlib import Path

doc = json.loads(Path(".pandas-source-report.json").read_text())
ledger = doc["sourceLedger"]
audits = doc["sourceAudits"]
package = [
    audit
    for audit in audits
    if audit.get("role") == "python.package-source"
    and audit.get("package") == "pandas"
]
if len(package) != 1:
    raise SystemExit(f"FAIL: expected one pandas package audit, got {len(package)}")
package = package[0]
totals = package["totals"]
if package.get("accounting_mode") != "structural":
    raise SystemExit(f"FAIL: expected structural package accounting, got {package.get('accounting_mode')!r}")
if package.get("loci_elided") is not True or "loci" in package:
    raise SystemExit("FAIL: pandas package audit should use compact elided loci")
if package.get("package_file_count", 0) < 1000:
    raise SystemExit(f"FAIL: package audit did not walk all pandas files: {package.get('package_file_count')}")
if totals.get("source_loci", 0) < 1_000_000:
    raise SystemExit(f"FAIL: pandas package source loci unexpectedly small: {totals}")
if totals.get("unclassified_source", 0) <= 0:
    raise SystemExit(f"FAIL: expected pandas unclassified source backlog: {totals}")
if totals.get("source_warranted", 0) <= 0:
    raise SystemExit(f"FAIL: expected at least the seeded source warrant replayed into package accounting: {totals}")
counts = package.get("ast_type_counts", {}).get("unclassified", {})
for kind in ("Name", "Call", "Assign"):
    if counts.get(kind, 0) <= 0:
        raise SystemExit(f"FAIL: missing unclassified AST bucket {kind}: {counts}")
constant = [
    audit
    for audit in audits
    if audit.get("role") == "python.constant-universe"
    and audit.get("source_memento", {}).get("source_function_name") == "BooleanDtype.__repr__"
]
if len(constant) != 1:
    raise SystemExit(f"FAIL: expected BooleanDtype.__repr__ source warrant, got {len(constant)}")
source_file = constant[0]["source_memento"]["file"]
if "pandas/core/arrays/boolean.py" not in source_file:
    raise SystemExit(f"FAIL: source warrant points at wrong file: {source_file}")
print("pandas source ledger:", ledger)
print("pandas package totals:", totals)
print(
    "top unclassified AST buckets:",
    sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10],
)
PY

echo ""
echo "==== pandas-source-accounting: PASS ===="
