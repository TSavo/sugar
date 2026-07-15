#!/usr/bin/env bash
# numpy VENDOR: ship a .proof + a witness package for the whole library.
#
# Imagine you are the numpy maintainer. You want to start shipping correctness:
# a signed `.proof` of your surface and a witness package of your passing tests,
# so any consumer can `verify` it -- recomputing, trusting nothing.
#
# This run does exactly that, with NO CODE CHANGES to numpy and NO HAND-WRITTEN
# SHIM:
#
#   SUGAR     — the universal lifter reads numpy's installed python source and
#               lifts every module-level function as sugar (symbol = qualified
#               path, e.g. `lib._function_base_impl.rot90`). Lean SourceMemento
#               mode: the `.proof` carries CIDs + spans, NOT inline bodies; the
#               body is resolved on demand from the installed numpy. ~2900
#               functions, one ~14MB `.proof`, ~16s. numpy.add is a C ufunc with
#               no python body -- it is simply not among the python functions
#               lifted; the thousands that ARE python all lift.
#   WITNESS   — the pytest-witness kit RUNS a numpy test and content-addresses
#               the run into a signed WitnessMemento. The run body is written to
#               a CID-named witness PACKAGE (`.sugar/witnesses/<cid>.witness`),
#               deployed separately (audit material, not ship material).
#   VERIFY    — the consumer side. ALL verification lives in the rust CLI. The
#               kit oracle (python) is UNTRUSTED: over RPC it only RESOLVES the
#               witness body; rust blake3's it ITSELF and compares to the pinned
#               CID. A body that does not recompute is refused, loudly.
#
# Scope note (no silent caps): this demo sugar-lifts ALL of numpy but RUNS ONE
# numpy test for the witness (the flow is identical per test; numpy's full suite
# is 179 files and minutes long). Point pytest-witness at more tests to scale.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"
PP="$REPO/implementations/python/sugar-lift-python-source/src:$REPO/implementations/python/sugar-lift-py-tests/src"
VENV="${NUMPY_WITNESS_VENV:-/tmp/numpy-witness-venv}"

needs_python_env=0
if [ ! -x "$VENV/bin/python" ]; then
  needs_python_env=1
elif ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import numpy
import pytest
import sugar_lift_py_tests
import sugar_lift_python_source
import sugar_pytest_witness
PY
then
  needs_python_env=1
fi

if [ "$needs_python_env" = "1" ]; then
  python3 -m venv --clear "$VENV"
  "$VENV/bin/python" -m pip install -q numpy pytest pynacl blake3 \
    -e "$REPO/implementations/python/sugar-lift-py-tests" \
    -e "$REPO/implementations/python/sugar-lift-python-source" \
    -e "$REPO/implementations/python/sugar-lift-py-pytest-witness"
fi
NUMPY_DIR="$("$VENV/bin/python" -c 'import numpy,os;print(os.path.dirname(numpy.__file__))')"

echo "== stage the vendor lift config in numpy's own tree =="
# The bind lifter only READS source (AST); it does not import numpy. working_dir
# is a NEUTRAL path so the kit's own imports are not shadowed by numpy/typing.
mkdir -p "$NUMPY_DIR/.sugar/lift/python-bind"
cat > "$NUMPY_DIR/.sugar/config.toml" <<EOF
[[plugins]]
name = "python-bind-lift"
kind = "lift"
surface = "python-bind"
[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
EOF
cat > "$NUMPY_DIR/.sugar/lift/python-bind/manifest.toml" <<EOF
name = "python-bind-lift"
version = "0.1.0"
kind = "lift"
command = ["/usr/bin/env", "SUGAR_LEAN_SOURCE=1", "PYTHONPATH=$PP", "$VENV/bin/python", "-m", "sugar_lift_python_source.bind_rpc", "--rpc"]
working_dir = "$REPO"
[capabilities]
authoring_surfaces = ["python-bind"]
EOF

echo "== sugar-lift ALL numpy -> numpy.proof (lean: CIDs, not inline bodies) =="
mkdir -p "$HERE/out"
rm -f "$HERE"/out/*.proof
time "$BIN" mint --project "$NUMPY_DIR" --out "$HERE/out" --library-bindings --quiet
PROOF="$(ls "$HERE"/out/*.proof)"
echo "  numpy.proof: $(du -h "$PROOF" | cut -f1), $("$BIN" dump "$PROOF" 2>/dev/null | grep -oE 'members *: *[0-9]+' | grep -oE '[0-9]+') sugar members"

echo "== a numpy consumer + its test (code file separate from the test) =="
cd "$HERE"
rm -rf .sugar/witnesses
rm -f ./blake3-512*.proof   # clean stale witness .proofs (verify loads all in the dir)
# numpy_consumer.py is the CODE under test; the witness binds to ITS code CID.
cat > numpy_consumer.py <<'PY'
import numpy as np


def add(a, b):
    return int(np.add(a, b))


def total(xs):
    return int(np.sum(xs))
PY
cat > test_numpy_consumer.py <<'PY'
from numpy_consumer import add, total


def test_add():
    assert add(2, 3) == 5


def test_total():
    assert total([1, 2, 3, 4]) == 10
PY

echo "== mint the witness .proof (the signed pointer the consumer verifies) =="
mkdir -p .sugar/lift/python-pytest-witness
cat > .sugar/config.toml <<EOF
[[plugins]]
name = "pytest-witness-lift"
kind = "lift"
surface = "python-pytest-witness"
[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
EOF
cat > .sugar/lift/python-pytest-witness/manifest.toml <<EOF
name = "pytest-witness-lift"
version = "0.1.0"
kind = "lift"
command = ["/usr/bin/env", "PYTHONPATH=$PP", "$VENV/bin/python", "-m", "sugar_pytest_witness.lift_lsp"]
resolve_witness_command = ["/usr/bin/env", "PYTHONPATH=$PP", "$VENV/bin/python", "-m", "sugar_pytest_witness.lift_lsp"]
resolve_witness_method = "sugar.plugin.resolve_witness"
working_dir = "$HERE"
[capabilities]
authoring_surfaces = ["python-pytest-witness"]
EOF
PATH="$VENV/bin:$PATH" "$BIN" mint --project . --out . --quiet

echo "== ship the witness PACKAGE (CID-named body, deployed separately) =="
# Same code_files the mint's lift used (non-test .py) -> same witness CID, so the
# package body content-addresses to the pinned CID. This is the audit material;
# the .proof carries only the signed pointer.
PYTHONPATH="$PP" "$VENV/bin/python" - <<PY
from sugar_pytest_witness import run_and_witness, write_witness_package
w = run_and_witness(".", "test_numpy_consumer.py", ["numpy_consumer.py"])
p = write_witness_package([w], ".sugar/witnesses")
print("  witness:", w.outcome, w.cid[:34], "->", p[0])
PY

echo "== VERIFY (consumer): rust recomputes; the kit oracle is untrusted =="
PATH="$VENV/bin:$PATH" "$BIN" verify --project .
