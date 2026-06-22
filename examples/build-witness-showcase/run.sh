#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$REPO/implementations/rust/target/debug/sugar"
VENV="${BUILD_WITNESS_VENV:-/tmp/build-witness-venv}"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q \
    -e "$REPO/implementations/python/sugar-lift-py-tests" \
    -e "$REPO/implementations/python/sugar-build-witness" \
    pytest pynacl blake3 cbor2
fi

if [ ! -x "$BIN" ]; then
  echo "== build local sugar debug CLI =="
  cargo build --manifest-path "$REPO/implementations/rust/Cargo.toml" -p sugar-cli --bin sugar >/dev/null
fi

WORK="$HERE/.work"
rm -rf "$WORK"
mkdir -p "$WORK"

render_sugar_project() {
  local fixture="$1"
  local suite="${2:-$1}"
  local dir="$WORK/$suite"
  cp -R "$HERE/fixtures/$fixture" "$dir"
  mkdir -p "$dir/.sugar/lift/build-witness"
  cat > "$dir/.sugar/config.toml" <<'TOML'
[[plugins]]
name = "build-witness-lift"
kind = "lift"
surface = "build-witness"

[solvers]
default = "z3"
[solvers.dispatch]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
TOML
  cat > "$dir/.sugar/lift/build-witness/manifest.toml" <<TOML
name = "build-witness-lift"
version = "0.1.0-draft"
protocol_version = "pep/1.7.0"
kind = "lift"
command = [
    "/usr/bin/env",
    "PYTHONPATH=$REPO/implementations/python/sugar-build-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src",
    "$VENV/bin/python",
    "-m",
    "sugar_build_witness.lift_lsp",
]
resolve_witness_command = [
    "/usr/bin/env",
    "PYTHONPATH=$REPO/implementations/python/sugar-build-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src",
    "$VENV/bin/python",
    "-m",
    "sugar_build_witness.lift_lsp",
]
resolve_witness_method = "sugar.plugin.resolve_witness"
working_dir = "."

[capabilities]
authoring_surfaces = ["build-witness"]
TOML
}

extract_json_receipt() {
  "$VENV/bin/python" - "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

src, dst = sys.argv[1], sys.argv[2]
text = Path(src).read_text(encoding="utf-8")
decoder = json.JSONDecoder()
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, _ = decoder.raw_decode(text[i:])
    except json.JSONDecodeError:
        continue
    Path(dst).write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    raise SystemExit(0)
raise SystemExit("no JSON receipt found")
PY
}

check_receipt() {
  local suite="$1" expected_script="$2" expected_output="$3" expected_rc="$4"
  local dir="$WORK/$suite"
  "$VENV/bin/python" - "$dir/.verify.json" "$suite" "$expected_script" "$expected_output" "$expected_rc" <<'PY'
import json
import sys

path, suite, expected_script, expected_output, expected_rc = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
build_rows = [r for r in rows if (r.get("property") or "").startswith("consistency:build-witness:")]
script_rows = [
    r for r in build_rows
    if "repo-script-cid-equals-distributed-script-cid" in (r.get("property") or "")
]
output_rows = [
    r for r in build_rows
    if "distributed-output-cid-equals-rebuilt-output-cid" in (r.get("property") or "")
]
if len(script_rows) != 1 or len(output_rows) != 1:
    raise SystemExit(
        f"{suite}: expected one script row and one output row, got "
        f"{len(script_rows)} script and {len(output_rows)} output"
    )
script, output = script_rows[0], output_rows[0]
if script.get("status") != expected_script:
    raise SystemExit(f"{suite}: expected script {expected_script}, got {script}")
if output.get("status") != expected_output:
    raise SystemExit(f"{suite}: expected output {expected_output}, got {output}")
if expected_rc == "0" and receipt.get("ok") is not True:
    raise SystemExit(f"{suite}: expected ok=true")
if expected_rc != "0" and receipt.get("ok") is not False:
    raise SystemExit(f"{suite}: expected ok=false")
witnesses = receipt.get("witnessDimension", {}).get("witnesses", [])
if len(witnesses) != 1:
    raise SystemExit(f"{suite}: expected one witnessDimension entry, got {len(witnesses)}")
w = witnesses[0]
if w.get("verdict") != "verified":
    raise SystemExit(f"{suite}: witnessDimension did not verify: {w}")
if "content-address:recompute" not in (w.get("checks") or []):
    raise SystemExit(f"{suite}: witness did not recompute: {w}")
print(
    f"{suite}: script={script.get('status')} output={output.get('status')} ok={receipt.get('ok')} "
    f"witness={w.get('verdict')} checks={','.join(w.get('checks') or [])}"
)
PY
}

check_tampered_receipt() {
  local suite="$1" reason_substr="$2"
  local dir="$WORK/$suite"
  "$VENV/bin/python" - "$dir/.verify.json" "$suite" "$reason_substr" <<'PY'
import json
import sys

path, suite, reason_substr = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
build_rows = [r for r in rows if (r.get("property") or "").startswith("consistency:build-witness:")]
script_rows = [
    r for r in build_rows
    if "repo-script-cid-equals-distributed-script-cid" in (r.get("property") or "")
]
output_rows = [
    r for r in build_rows
    if "distributed-output-cid-equals-rebuilt-output-cid" in (r.get("property") or "")
]
if len(script_rows) != 1 or len(output_rows) != 1:
    raise SystemExit(
        f"{suite}: expected one script row and one output row, got "
        f"{len(script_rows)} script and {len(output_rows)} output"
    )
if script_rows[0].get("status") != "discharged" or output_rows[0].get("status") != "discharged":
    raise SystemExit(f"{suite}: stale proof equality rows should stay discharged: {build_rows}")
witnesses = receipt.get("witnessDimension", {}).get("witnesses", [])
if len(witnesses) != 1:
    raise SystemExit(f"{suite}: expected one witnessDimension entry, got {len(witnesses)}")
w = witnesses[0]
if w.get("verdict") != "refused":
    raise SystemExit(f"{suite}: expected witness refused, got {w}")
if "witness did not reproduce" not in (w.get("reason") or ""):
    raise SystemExit(f"{suite}: witness refusal did not name recompute drift: {w}")
print(
    f"{suite}: script={script_rows[0].get('status')} output={output_rows[0].get('status')} "
    f"ok={receipt.get('ok')} "
    f"witness={w.get('verdict')} checks={','.join(w.get('checks') or [])}"
)
PY
}

write_lying_discharge() {
  cat > "$WORK/lying_discharge.py" <<'PY'
import json

print(json.dumps({"verdict": "DISCHARGED", "reason": "lying oracle"}))
PY
}

force_lying_discharge() {
  local dir="$1"
  "$VENV/bin/python" - "$dir/.sugar/lift/build-witness/manifest.toml" "$VENV/bin/python" "$WORK/lying_discharge.py" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
python = sys.argv[2]
script = sys.argv[3]
text = path.read_text(encoding="utf-8")
replacement = (
    "discharge_command = [\n"
    f"    \"{python}\",\n"
    f"    \"{script}\",\n"
    "]\n"
    "witness_tool = \"build\"\n"
)
marker = "resolve_witness_command = ["
if "discharge_command = [" in text:
    start = text.index("discharge_command = [")
    end = text.index("]\n", start) + 2
    text = text[:start] + text[end:]
    text = text.replace("witness_tool = \"build\"\n", "")
path.write_text(text.replace(marker, replacement + marker), encoding="utf-8")
PY
}

run_suite() {
  local suite="$1" expected_script="$2" expected_output="$3"
  local dir="$WORK/$suite"
  render_sugar_project "$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.verify.raw" "$dir/.verify.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/.build"

  echo "== mint $suite =="
  (cd "$dir" && "$BIN" mint --out . --quiet)

  echo "== verify $suite =="
  set +e
  (cd "$dir" && PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json) > "$dir/.verify.raw" 2>&1
  local rc=$?
  set -e
  extract_json_receipt "$dir/.verify.raw" "$dir/.verify.json"
  local expected_rc=1
  if [ "$expected_script" = "discharged" ] && [ "$expected_output" = "discharged" ]; then
    expected_rc=0
  fi
  if [ "$rc" -ne "$expected_rc" ]; then
    echo "$suite expected verify exit $expected_rc, got $rc" >&2
    cat "$dir/.verify.raw" >&2
    exit 1
  fi
  check_receipt "$suite" "$expected_script" "$expected_output" "$expected_rc"
}

run_lying_oracle_regression() {
  local suite="$1" expected_script="$2" expected_output="$3"
  local dir="$WORK/$suite"
  force_lying_discharge "$dir"

  echo "== verify $suite with lying discharge oracle =="
  set +e
  (cd "$dir" && PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json) > "$dir/.verify.lie.raw" 2>&1
  local rc=$?
  set -e
  extract_json_receipt "$dir/.verify.lie.raw" "$dir/.verify.lie.json"
  if [ "$rc" -ne 1 ]; then
    echo "$suite lying-oracle expected verify exit 1, got $rc" >&2
    cat "$dir/.verify.lie.raw" >&2
    exit 1
  fi
  check_receipt "$suite" "$expected_script" "$expected_output" 1
}

run_tampered_script_suite() {
  local suite="tampered-script"
  local dir="$WORK/$suite"
  rm -rf "$dir"
  render_sugar_project good "$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.verify.raw" "$dir/.verify.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/.build"

  echo "== mint $suite from clean script =="
  (cd "$dir" && "$BIN" mint --out . --quiet)
  cat >> "$dir/distributed/configure.py" <<'PY'
# post-mint script tamper
PY

  echo "== verify $suite after script tamper =="
  set +e
  (cd "$dir" && PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json) > "$dir/.verify.raw" 2>&1
  local rc=$?
  set -e
  extract_json_receipt "$dir/.verify.raw" "$dir/.verify.json"
  if [ "$rc" -ne 1 ]; then
    echo "$suite expected verify exit 1, got $rc" >&2
    cat "$dir/.verify.raw" >&2
    exit 1
  fi
  check_tampered_receipt "$suite" "distributed script CID mismatch"
}

run_tampered_output_suite() {
  local suite="tampered-output"
  local dir="$WORK/$suite"
  rm -rf "$dir"
  render_sugar_project good "$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.verify.raw" "$dir/.verify.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/.build"

  echo "== mint $suite from clean artifact =="
  (cd "$dir" && "$BIN" mint --out . --quiet)
  cat > "$dir/distributed/libdemo.txt" <<'TXT'
demo-lib
message=owned
version=1
TXT

  echo "== verify $suite after artifact tamper =="
  set +e
  (cd "$dir" && PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json) > "$dir/.verify.raw" 2>&1
  local rc=$?
  set -e
  extract_json_receipt "$dir/.verify.raw" "$dir/.verify.json"
  if [ "$rc" -ne 1 ]; then
    echo "$suite expected verify exit 1, got $rc" >&2
    cat "$dir/.verify.raw" >&2
    exit 1
  fi
  check_tampered_receipt "$suite" "output artifact CID mismatch"
}

write_lying_discharge

run_suite good discharged discharged
run_suite bad-script unsatisfied discharged
run_lying_oracle_regression bad-script unsatisfied discharged
run_suite bad-output discharged unsatisfied
run_lying_oracle_regression bad-output discharged unsatisfied
run_tampered_script_suite
run_tampered_output_suite

echo "PASS: build witness recomputes deterministic builds and refuses script/output drift."
