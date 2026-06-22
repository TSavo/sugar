#!/usr/bin/env bash
# The numpy showcase showdown: all the verbs over one operation, numpy.rot90.
#
#   sugar-lift  — the universal lifter reads numpy's INSTALLED python source and
#                 lifts numpy.rot90 as sugar into a lean .proof (CIDs + spans, no
#                 inline bodies) staged in .sugar/imports/. The symbol is the
#                 PUBLIC name (`numpy.rot90`), derived from numpy's __init__
#                 re-exports; the SourceMemento still points at the real source
#                 (lib/_function_base_impl.py), so the oracle resolves the body
#                 from the installed numpy on demand. (numpy.add is a C ufunc with
#                 no python body -- rot90 is real python, which is why it lifts.)
#   materialize — a @boundary(numpy.rot90) stub gets its body filled with rot90's
#                 REAL body, resolved by the source oracle from installed numpy.
#   recognize   — a production np.rot90 callsite is found from the sugar .proof
#                 by PUBLIC SYMBOL (alias-resolved, anywhere).
#   mint        — three lift surfaces conjoin into one .proof: sugar (python-bind,
#                 code IDENTITY) + contract (numpy.testing, the PROPOSITION) +
#                 witness (pytest-witness, the EVIDENCE).
#   prove       — the GOOD test discharges two ways (numpy.testing z3 CONSISTENT
#                 AND pytest-witness WITNESSED); the degenerate test (the same
#                 rot90 element asserted == 2 AND == 9) is REFUSED both ways
#                 (z3 UNSAT AND the witness run 'failed').
#
# Everything is kit-side; the .proof is the transport; rust stays proof-blind.
# NOTE: no `set -e`. `prove` exits nonzero on the (expected) degenerate refusal,
# exactly like pandas-showcase; this script captures the report and PASSES iff
# sugar produces the right verdict (good proved both ways, degenerate refused).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$REPO/implementations/rust/target/debug/sugar"
PP="$REPO/implementations/python/sugar-lift-python-source/src:$REPO/implementations/python/sugar-lift-py-tests/src"

# The pytest-witness lifter RUNS numpy's test, and the numpy.testing lifter
# introspects numpy.testing to classify the assertion vocabulary -- both need
# numpy in a venv (PEP 668: never --break-system-packages). The lift manifests
# point their interpreter at this venv.
VENV="${NUMPY_WITNESS_VENV:-/tmp/numpy-witness-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q numpy pytest pynacl blake3 cbor2 \
    -e "$REPO/implementations/python/sugar-lift-py-tests" \
    -e "$REPO/implementations/python/sugar-lift-python-source" \
    -e "$REPO/implementations/python/sugar-lift-py-pytest-witness"
fi
NUMPY_DIR="$("$VENV/bin/python" -c 'import numpy,os;print(os.path.dirname(numpy.__file__))')"

cd "$HERE"
rm -f blake3-512_*.proof 2>/dev/null || true
rm -rf .sugar/runs .sugar/witnesses 2>/dev/null || true
rm -f .sugar/imports/*.proof 2>/dev/null || true
# Restore the @boundary stub (materialize rewrites it in place; a re-run needs
# the unfilled stub back).
cat > boundary.py <<'PY'
from sugar import boundary


@boundary(library="numpy", call="rot90")
def my_rot90(m):
    raise NotImplementedError
PY

echo "== sugar-lift numpy -> .sugar/imports/ (lean: CIDs, not inline bodies) =="
# Stage the universal-lift config in numpy's own installed tree (mirrors
# numpy-vendor). The bind lifter only READS source (AST); working_dir is a
# NEUTRAL path so the kit's own imports are not shadowed by numpy/typing.
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
command = ["/usr/bin/env", "SUGAR_LEAN_SOURCE=1", "PYTHONPATH=$PP", "$VENV/bin/python", "-m", "sugar_lift_python_source.bind_rpc"]
working_dir = "$REPO"
[capabilities]
authoring_surfaces = ["python-bind"]
EOF
mkdir -p .sugar/imports
"$BIN" mint --project "$NUMPY_DIR" --out .sugar/imports --library-bindings --quiet
NUMPY_PROOF="$(ls .sugar/imports/*.proof)"
echo "  numpy sugar .proof: $(du -h "$NUMPY_PROOF" | cut -f1) (public symbol numpy.rot90, lean SourceMemento)"

echo "== materialize @boundary(numpy.rot90) (body resolved by the oracle) =="
# Run via the venv python: the source oracle locates the installed numpy by the
# binding's library tag, and the system python3 has no numpy.
PYTHONPATH="$PP" "$VENV/bin/python" -c "
from sugar_lift_python_source.bind_rpc import dispatch
r=dispatch({'jsonrpc':'2.0','id':1,'method':'sugar.plugin.materialize','params':{'project_root':'.','source_paths':['boundary.py'],'write':True}})
res=r['result']['results'][0]
print(' ', res['outcome'], res.get('materialized'))"

echo "== recognize np.rot90 in app.py (by public symbol) =="
"$BIN" recognize --surface python-bind --target python --project . --source app.py --json 2>/dev/null \
  | "$VENV/bin/python" -c "import sys,json;[print('  recognized',t['symbol'],'tier',t['match_tier']) for t in json.load(sys.stdin)['tags']]"

echo "== mint ALL THREE lifters -> one .proof =="
# sugar (python-bind, code IDENTITY) + contract (numpy.testing, the PROPOSITION)
# + witness (pytest-witness, the EVIDENCE).
"$BIN" mint --out . --library-bindings >/dev/null

echo "== prove (consistency AND witness) =="
report="$(PATH="$VENV/bin:$PATH" "$BIN" prove . 2>/dev/null)"
echo "$report"

echo ""
echo "== self-check: sugar must prove the good rot90 contract and refuse the degenerate both ways =="
fail=0
check_text() {
  local haystack="$1" label="$2" pattern="$3"
  # Avoid `echo "$report" | grep -q` under pipefail: grep can exit early
  # after a match, then echo may SIGPIPE and make a present verdict look absent.
  if grep -q "$pattern" <<<"$haystack"; then echo "  ok: $label"; else echo "  MISSING: $label ($pattern)"; fail=1; fi
}
check() { check_text "$report" "$1" "$2"; }
# Consistency axis: the good rot90 element facts discharge; the contradiction is UNSAT.
check "consistency discharges rot90 element facts"  "consistent about callsite .test_rot90_quarter_turn"
check "consistency REFUSES the contradiction"       "contradictory about callsite .test_rot90_contradiction"
# Witness axis: rust parses the package body; the good test passed in it, the degenerate failed.
check "witness REFUSES the degenerate from package body" "witness REFUSED by rust package body"
check "witness names the failing degenerate test"   "test_rot90_contradiction"

echo ""
echo "== verify durable artifact (expected refusal: the degenerate twin is in this proof) =="
verify_report="$(PATH="$VENV/bin:$PATH" "$BIN" verify --project . --json 2>&1)"
verify_rc=$?
echo "$verify_report"
if [ "$verify_rc" -eq 0 ]; then
  echo "  MISSING: durable verify must refuse the expected degenerate twin"
  fail=1
else
  echo "  ok: durable verify refused the expected degenerate twin (exit $verify_rc)"
fi
check_text "$verify_report" "durable verify preserves good rot90 discharge" "consistent about callsite .test_rot90_quarter_turn"
check_text "$verify_report" "durable verify preserves contradiction refusal" "contradictory about callsite .test_rot90_contradiction"
check_text "$verify_report" "durable verify recomputes witness package" '"verdict": "verified"'

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: numpy.rot90 proved correct (consistency AND witness); the degenerate refused both ways."
else
  echo "FAIL: sugar did not produce the expected verdict."; exit 1
fi
