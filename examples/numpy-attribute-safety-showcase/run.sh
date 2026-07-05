#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
SUGAR=""
VENV="${NUMPY_ATTR_SHOWCASE_VENV:-/tmp/sugar-numpy-attribute-safety-venv}"
PYTHON="$VENV/bin/python"
PIP="$PYTHON -m pip"
NUMPY_VERSION="2.4.6"
STAMP="$VENV/.numpy-attribute-safety-${NUMPY_VERSION}.stamp"

for suite in good bad; do
  if [ ! -d "$HERE/$suite" ]; then
    echo "missing suite directory: $HERE/$suite" >&2
    exit 1
  fi
done

if [ "${NUMPY_ATTR_SHOWCASE_ON_REMOTE:-0}" != "1" ] \
  && [ "${NUMPY_ATTR_SHOWCASE_USE_BCARGO:-1}" != "0" ] \
  && [ "$(uname -s)" != "Linux" ]; then
  echo "== run numpy attribute-safety showcase on battleaxe via bcargo =="
  "$REPO/bin/bcargo" build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar >/dev/null

  remote_host="${BCARGO_REMOTE_HOST:-battleaxe}"
  remote_tag="$(printf '%s' "$(cd "$REPO" && pwd -P)" | shasum 2>/dev/null | cut -c1-12)"
  remote_tag="${remote_tag:-default}"
  remote_root="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-${remote_tag}}"
  remote_repo="$remote_root/sugar"
  remote_cmd="cd $(printf '%q' "$remote_repo") && NUMPY_ATTR_SHOWCASE_ON_REMOTE=1 NUMPY_ATTR_SHOWCASE_SKIP_LOCAL_BUILD=1 examples/numpy-attribute-safety-showcase/run.sh"
  ssh -o BatchMode=yes "$remote_host" "bash -lc $(printf '%q' "$remote_cmd")"
  exit $?
fi

SUGAR="$("$REPO/bin/sugarbin" --profile release)"

if [ ! -x "$SUGAR" ]; then
  echo "missing executable: $SUGAR" >&2
  exit 1
fi

echo "SCOPE: this showcase proves Python attribute read/access presence via classShapes + pytest witness."
echo "SCOPE: it does NOT claim whole-program panic-freedom; __init__ attribute-write panic loci remain undecidable and out of scope."

needs_python_env=0
if [ ! -x "$PYTHON" ] || [ ! -f "$STAMP" ]; then
  needs_python_env=1
elif ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import numpy
import sugar_lift_py_tests
import sugar_lift_python_source
import sugar_pytest_witness
PY
then
  needs_python_env=1
fi

if [ "$needs_python_env" = "1" ]; then
  echo "== prepare python witness environment =="
  python3 -m venv --clear "$VENV"
  $PIP install --quiet --upgrade pip
  $PIP install --quiet --no-cache-dir \
    "numpy==$NUMPY_VERSION" \
    pytest pynacl blake3 cbor2 \
    -e "$REPO/implementations/python/sugar-lift-py-tests" \
    -e "$REPO/implementations/python/sugar-lift-python-source" \
    -e "$REPO/implementations/python/sugar-lift-py-pytest-witness"
  mkdir -p "$VENV"
  touch "$STAMP"
fi

render_one() {
  local template="$1"
  local output="$2"
  local suite_dir="$3"
  if [ ! -f "$template" ]; then
    echo "missing manifest template: $template" >&2
    exit 1
  fi
  sed \
    -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@SUITE_SRC@|$suite_dir/src|g" \
    "$template" > "$output"
}

render_manifests() {
  local suite="$1"
  local suite_dir="$HERE/$suite"
  local base="$suite_dir/.sugar/lift"
  render_one \
    "$base/python-source/manifest.toml.in" \
    "$base/python-source/manifest.toml" \
    "$suite_dir"
  render_one \
    "$base/python-pytest-witness/manifest.toml.in" \
    "$base/python-pytest-witness/manifest.toml" \
    "$suite_dir"
}

clean_suite() {
  local suite="$1"
  local dir="$HERE/$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.prove.json" "$dir/.verify.json" "$dir/.verify_recompute.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/.pytest_cache" "$dir/src/__pycache__" "$dir/tests/__pycache__"
}

json_from_file() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    raise SystemExit("no JSON object found")
print(json.dumps(json.loads(text[match.start():])))
PY
}

check_prove_report() {
  local path="$1"
  local suite="$2"
  local expected_attr="$3"
  local expected_witness="$4"
  python3 - "$path" "$suite" "$expected_attr" "$expected_witness" <<'PY'
import json
import re
import sys

path, suite, expected_attr, expected_witness = sys.argv[1:5]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    raise SystemExit(f"{suite}: no JSON report found")
data = json.loads(text[match.start():])
rows = data.get("rows") or []

attr_rows = [
    r for r in rows
    if (r.get("reason") or "").startswith("attribute-safety:")
]
if not attr_rows:
    raise SystemExit(f"{suite}: missing attribute-safety rows")

witness_rows = [
    r for r in rows
    if "witness-package" in (r.get("property") or "") or "witness" in (r.get("reason") or "").lower()
]
if not witness_rows:
    raise SystemExit(f"{suite}: missing pytest witness row")

attr_discharged = sum(1 for r in attr_rows if r.get("status") == "discharged")
attr_refused = [r for r in attr_rows if r.get("status") != "discharged"]
witness_statuses = [r.get("status") for r in witness_rows]
other_undecidable = [
    r for r in rows
    if r not in attr_rows
    and r not in witness_rows
    and r.get("status") != "discharged"
]

if expected_attr == "discharged":
    if attr_refused:
        raise SystemExit(f"{suite}: expected all attribute rows discharged, got {attr_rows}")
    if not all("classShapes guaranteed-present" in (r.get("reason") or "") for r in attr_rows):
        raise SystemExit(f"{suite}: discharged attribute rows did not cite classShapes guarantees: {attr_rows}")
else:
    if not attr_refused:
        raise SystemExit(f"{suite}: expected at least one refused attribute row, got {attr_rows}")
    if not any("not a guaranteed-present" in (r.get("reason") or "") for r in attr_refused):
        raise SystemExit(f"{suite}: refused attribute row did not name the classShapes falsePass guard: {attr_refused}")

if expected_witness == "discharged":
    if any(status != "discharged" for status in witness_statuses):
        raise SystemExit(f"{suite}: expected witness discharged, got {witness_rows}")
else:
    if any(status == "discharged" for status in witness_statuses):
        raise SystemExit(f"{suite}: expected witness refusal, got {witness_rows}")

print(
    f"{suite}: attr_discharged={attr_discharged} "
    f"attr_refused={len(attr_refused)} witness_statuses={','.join(str(s) for s in witness_statuses)} "
    f"out_of_scope_undecidable_rows={len(other_undecidable)}"
)
if other_undecidable:
    files = sorted(
        {
            f"{r.get('file')}:{r.get('line')}"
            for r in other_undecidable
            if r.get("file") and r.get("line")
        }
    )
    print(
        f"{suite}: scope note: {len(other_undecidable)} non-attribute-safety rows remain undecidable "
        f"({', '.join(files)}); these are not counted as proved by this attribute read/access showcase."
    )
PY
}

witness_verdict() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])
for witness in data.get("witnessDimension", {}).get("witnesses", []):
    verdict = witness.get("verdict")
    if verdict:
        print(verdict)
        raise SystemExit(0)
print("MISSING")
PY
}

run_pytest_axis() {
  local suite="$1"
  local expected="$2"
  local dir="$HERE/$suite"
  local out="$HERE/.pytest-$suite.out"

  set +e
  (cd "$dir" && PYTHONPATH="$dir/src" "$PYTHON" -m pytest -q tests) > "$out" 2>&1
  local rc=$?
  set -e

  if [ "$expected" = "pass" ]; then
    if [ "$rc" -ne 0 ]; then
      echo "$suite pytest expected pass" >&2
      cat "$out" >&2
      exit 1
    fi
  else
    if [ "$rc" -eq 0 ]; then
      echo "$suite pytest expected AttributeError refusal" >&2
      cat "$out" >&2
      exit 1
    fi
    if ! grep -q "AttributeError" "$out"; then
      echo "$suite pytest failed, but not with AttributeError" >&2
      cat "$out" >&2
      exit 1
    fi
  fi
  echo "$suite pytest=$expected"
}

run_suite() {
  local suite="$1"
  local expect_attr="$2"
  local expect_witness="$3"
  local expect_pytest="$4"
  local dir="$HERE/$suite"

  render_manifests "$suite"
  clean_suite "$suite"

  echo "== direct pytest $suite =="
  run_pytest_axis "$suite" "$expect_pytest"

  echo "== mint $suite =="
  (cd "$dir" && "$SUGAR" mint --out .) >/dev/null

  local proof
  proof="$(find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -print -quit)"
  if [ -z "$proof" ]; then
    echo "$suite did not mint a proof" >&2
    exit 1
  fi

  echo "== prove $suite =="
  set +e
  (cd "$dir" && "$SUGAR" prove . --json) > "$dir/.prove.json" 2>&1
  local prove_rc=$?
  set -e
  : "$prove_rc"

  check_prove_report "$dir/.prove.json" "$suite" "$expect_attr" "$expect_witness"

  if [ "$expect_witness" = "discharged" ]; then
    echo "== verify $suite witness =="
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify.json" 2>&1
    local verify_rc=$?
    set -e
    : "$verify_rc"
    local got_verdict
    got_verdict="$(witness_verdict "$dir/.verify.json")"
    if [ "$got_verdict" != "verified" ]; then
      echo "$suite witness verification expected verified, got $got_verdict" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi
  fi
}

run_suite good discharged discharged pass
run_suite bad refused refused fail

echo "numpy attribute-safety showcase self-check passed"
