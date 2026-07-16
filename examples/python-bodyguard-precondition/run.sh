#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
WORK="${PYTHON_BODYGUARD_WORK:-$HERE/.work}"
PY_SRC="$REPO/implementations/python/sugar-lift-python-source/src"
PY_TESTS="$REPO/implementations/python/sugar-lift-py-tests/src"
VENV="${PYTHON_BODYGUARD_VENV:-/tmp/python-bodyguard-precondition-venv}"
PYTHON="$VENV/bin/python"

echo "SCOPE: Python body guard -> precondition predicate, zero Python source changes outside the fixture."
echo "SCOPE: guard = if x < 2 or x > 36: raise ValueError(...)."
echo "SCOPE: proof property = caller value facts discharge/refuse callee precondition at the call seam."
echo "SCOPE: no raise, exception, panic, or control-flow semantics are modeled."
echo "SCOPE: federation = Python and Rust equivalent precondition formulas have the same canonical CID."

if ! command -v python3 >/dev/null 2>&1; then
  echo "missing python3" >&2
  exit 1
fi
if ! command -v z3 >/dev/null 2>&1; then
  echo "missing z3" >&2
  exit 1
fi

# The Python source lifter imports canonical.py, which imports blake3. CI runs
# this showcase with a bare system python3, so keep deps in a venv instead of
# touching the system interpreter (PEP 668).
if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$VENV"
fi
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import nacl
PY
then
  python3 -m venv --clear "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl
fi

echo "== resolve local proof binaries via sugarbin =="
SUGAR="${PYTHON_BODYGUARD_SUGAR:-$("$REPO/bin/sugarbin" --profile debug)}"
BIN_DIR="$(dirname "$SUGAR")"
WALK_RPC="${PYTHON_BODYGUARD_WALK_RPC:-$("$REPO/bin/sugarbin" --profile debug --bin sugar-walk-rpc)}"

for bin in "$SUGAR" "$WALK_RPC"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

export PYTHONPATH="$PY_SRC:$PY_TESTS${PYTHONPATH:+:$PYTHONPATH}"

rm -rf "$WORK"
mkdir -p "$WORK"

LIFT_WRAPPER="$WORK/sugar-lift-python-verify.sh"
cat > "$LIFT_WRAPPER" <<SH
#!/bin/sh
PYTHONPATH="$PY_SRC:$PY_TESTS\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec "$PYTHON" -c "from sugar_lift_python_source.verify_rpc import run_rpc; run_rpc()"
SH
chmod +x "$LIFT_WRAPPER"

write_suite() {
  local suite="$1"
  local arg="$2"
  local dir="$WORK/$suite"
  mkdir -p "$dir/.sugar/lift/python"

  cat > "$dir/bounded_digit.py" <<'PY'
def bounded_digit(x: int) -> int:
    if x < 2 or x > 36:
        raise ValueError("x out of range")
    return x
PY

  cat > "$dir/test_bounded_digit.py" <<PY
from bounded_digit import bounded_digit


def test_bounded_digit():
    assert bounded_digit($arg) == $arg
PY

  cat > "$dir/.sugar/config.toml" <<'TOML'
[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"

[solvers]
default = "z3"

[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"

[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
TOML

  cat > "$dir/.sugar/lift/python/manifest.toml" <<TOML
name = "python"
command = ["$LIFT_WRAPPER", "--rpc"]
working_dir = "."
TOML
}

extract_json_receipt() {
  "$PYTHON" - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
text = re.sub(r"\x1b\[[0-9;]*m", "", text)
decoder = json.JSONDecoder()
receipt = None
for index, char in enumerate(text):
    if char != "{":
        continue
    try:
        obj, _ = decoder.raw_decode(text[index:])
    except Exception:
        continue
    if isinstance(obj, dict) and obj.get("kind") == "verification-receipt":
        receipt = obj
        break
if receipt is not None:
    print(json.dumps(receipt, sort_keys=True))
    raise SystemExit(0)
raise SystemExit(1)
PY
}

verify_suite() {
  local suite="$1"
  local expected_status="$2"
  local dir="$WORK/$suite"

  rm -f "$dir"/blake3-512_*.proof "$dir/.verify.json" "$dir/.verify.raw"
  echo "== mint $suite =="
  (cd "$dir" && "$SUGAR" mint --out . --quiet)

  echo "== verify $suite =="
  set +e
  (cd "$dir" && "$SUGAR" verify --allow-failed-components --project . --json) > "$dir/.verify.raw" 2>&1
  local code=$?
  set -e
  extract_json_receipt "$dir/.verify.raw" > "$dir/.verify.json"

  "$PYTHON" - "$dir/.verify.json" "$dir/.verify.raw" "$suite" "$expected_status" "$code" <<'PY'
import json
import re
import sys

path, raw_path, suite, expected_status, code = sys.argv[1:6]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("claims") or receipt.get("rows") or []
raw = open(raw_path, encoding="utf-8").read()

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def mentions_bounded_digit(value):
    if isinstance(value, str):
        return "bounded_digit" in value
    if isinstance(value, (dict, list)):
        return any(mentions_bounded_digit(child) for child in (value.values() if isinstance(value, dict) else value))
    return False

seam_rows = [
    row
    for row in rows
    if row.get("bridge") == "bounded_digit" and row.get("callee") == "bounded_digit"
]
if not seam_rows:
    seam_rows = [row for row in rows if mentions_bounded_digit(row)]
status_words = {str(row.get("status")) for row in seam_rows if row.get("status")}
if not status_words:
    for obj in walk(receipt):
        if mentions_bounded_digit(obj) and obj.get("status"):
            status_words.add(str(obj["status"]))

if expected_status not in status_words:
    raw_match = re.search(
        rf"bounded_digit[\s\S]{{0,400}}\b{re.escape(expected_status)}\b|"
        rf"\b{re.escape(expected_status)}\b[\s\S]{{0,400}}bounded_digit",
        raw,
    )
    if raw_match:
        status_words.add(expected_status)

if expected_status not in status_words:
    raise SystemExit(
        f"{suite}: expected bounded_digit seam status {expected_status}, "
        f"got statuses={sorted(status_words)} rows={seam_rows} receipt={receipt}"
    )
claim = seam_rows[0] if seam_rows else {"status": expected_status}
status = claim.get("status")
if status is not None and status != expected_status:
    raise SystemExit(f"{suite}: expected status {expected_status}, got {status}: {claim}")

def is_expected_ambient_refusal(row):
    return (
        row.get("status") == "refused"
        and str(row.get("property", "")).startswith("consistency:")
        and "lacks required provenance KIND" in str(row.get("reason", ""))
    )

unexpected_failures = []
for row in rows:
    row_status = str(row.get("status", ""))
    if row_status in {"discharged", "proven", "consistent", "sat"}:
        continue
    if row is claim and expected_status in {"unsatisfied", "refused", "unsat"}:
        continue
    if is_expected_ambient_refusal(row):
        continue
    unexpected_failures.append(row)
if unexpected_failures:
    raise SystemExit(
        f"{suite}: unexpected verifier failures after seam check: "
        f"{unexpected_failures}"
    )
print(
    f"{suite} seam_status={expected_status} verify_rc={code} "
    f"ok={receipt.get('ok')} totalClaims={receipt.get('totalClaims')}"
)
PY
}

compare_federation_cids() {
  "$PYTHON" - "$WORK/good/bounded_digit.py" "$WORK/python-pre.json" <<'PY'
import json
import sys
from pathlib import Path

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.lifter import lift_source
from sugar_lift_python_source.verify_dialect import collect_int_signatures, to_verify_dialect

source = Path(sys.argv[1]).read_text(encoding="utf-8")
contract = next(
    item
    for item in lift_source(source, "bounded_digit.py").ir
    if item.get("kind") == "function-contract" and not str(item.get("fnName", "")).startswith("<source-unit")
)
pre = to_verify_dialect(contract, collect_int_signatures(source)["bounded_digit"])["pre"]
json.dump({"pre": pre, "cid": cid_of_json(pre)}, open(sys.argv[2], "w", encoding="utf-8"), sort_keys=True)
PY

  "$PYTHON" - "$WALK_RPC" "$WORK/rust-pre.json" <<'PY'
import json
import subprocess
import sys

from sugar_lift_python_source.canonical import cid_of_json

walk_rpc, out_path = sys.argv[1:3]
rust_source = """
fn bounded_digit(x: u32) -> u32 {
    assert!(x >= 2 && x <= 36);
    x
}
"""
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "walk.lift_pre",
    "params": {"src": rust_source, "fn_name": "bounded_digit"},
}
completed = subprocess.run(
    [walk_rpc],
    input=json.dumps(request) + "\n",
    capture_output=True,
    text=True,
    check=False,
)
if completed.returncode != 0:
    raise SystemExit(completed.stderr)
response = json.loads(completed.stdout.splitlines()[-1])
if "error" in response:
    raise SystemExit(response["error"])
pre = response["result"]
json.dump({"pre": pre, "cid": cid_of_json(pre)}, open(out_path, "w", encoding="utf-8"), sort_keys=True)
PY

  "$PYTHON" - "$WORK/python-pre.json" "$WORK/rust-pre.json" "$WORK/federation.json" <<'PY'
import json
import sys

python_path, rust_path, out_path = sys.argv[1:4]
python_pre = json.load(open(python_path, encoding="utf-8"))
rust_pre = json.load(open(rust_path, encoding="utf-8"))
result = {
    "python_pre_cid": python_pre["cid"],
    "rust_pre_cid": rust_pre["cid"],
    "equal": python_pre["cid"] == rust_pre["cid"],
    "python_pre": python_pre["pre"],
    "rust_pre": rust_pre["pre"],
}
json.dump(result, open(out_path, "w", encoding="utf-8"), indent=2, sort_keys=True)
if not result["equal"]:
    raise SystemExit(json.dumps(result, indent=2, sort_keys=True))
print(f"federation python_pre_cid={result['python_pre_cid']} rust_pre_cid={result['rust_pre_cid']} equal=true")
PY
}

write_suite good 16
write_suite bad 1

compare_federation_cids
verify_suite good discharged
verify_suite bad unsatisfied

echo "python bodyguard precondition showcase self-check passed"
echo "receipts: $WORK/good/.verify.json $WORK/bad/.verify.json"
echo "federation: $WORK/federation.json"
