#!/usr/bin/env bash
# The complete Python sole-construction floor set, as ONE measured section.
#
# WHY THIS IS A SCRIPT AND NOT TWENTY WORKFLOW STEPS
#
# It used to be twenty steps, each `if: always()`, so that one red axis never
# hid the others: the complete floor set always comes from one pinned run.
# Putting those twenty steps behind the machine-wide heavy lease one at a time
# would have taken and released the lease twenty times, letting a pandas census
# interleave between axes -- and then the "one pinned run" property would be a
# fiction. One lease, one pass over every axis, one verdict.
#
# `if: always()` semantics are preserved here, not abandoned: EVERY axis runs,
# failures are collected rather than short-circuited, and the script exits
# non-zero at the end if any axis was red. R > 0 ⇒ CI red, on every axis, and
# silence on an axis is never mistaken for zero.
#
# Usage: tools/run_sole_construction_floors.sh   (from the repo root)

set -uo pipefail

TESTS=implementations/python/sugar-lift-py-tests
SCRIPTS="$TESTS/scripts"

red_axes=()
green_axes=()

axis() {
  local name="$1"; shift
  echo "::group::$name"
  if "$@"; then
    green_axes+=("$name")
    echo "$name: GREEN"
  else
    local status=$?
    red_axes+=("$name (exit $status)")
    echo "::error::$name is RED (exit $status)"
  fi
  echo "::endgroup::"
}

# Permanent floors — baseline-free. R > 0 ⇒ CI red on every axis.
# See docs/contributing/python-sole-construction.md
# factory_zero_tolerance.py retired with factory/ (#6028): no dual construction
# door left to measure. Ownership + construction-panic catch remain permanent.
axis "R_ownership = 0" python "$SCRIPTS/factory_ownership_law.py"
axis "R_construction_panic_catches_outside_membrane = 0" \
  python "$SCRIPTS/construction_panic_catch_law.py"

# Heavy supervised enum floors — sequential, inside the one lease interval.
# Population: authenticated pandas corpus (NOT kit production_roots).
# Silent default to sugar-lift-py-tests src+scripts was a false green: R=0 on
# ~444 kit files while the corpus process floors never entered pandas.
# Scanners refuse empty path args; this binding must name the corpus root.
PANDAS_CORPUS="$(
  python -c 'from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus; print(authenticated_pandas_corpus().root)'
)" || {
  echo "::error::cannot authenticate pandas corpus for process floors"
  exit 1
}
echo "process-floor population: authenticated pandas corpus at $PANDAS_CORPUS"
# --repo-root must be the corpus root (not the Sugar checkout): relative loci
# and supervised-enum corpus_root are derived from it.
axis "R_native_crashes = 0" \
  python "$SCRIPTS/native_crash_zero_tolerance.py" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS"
axis "R_bare_exceptions = 0" \
  python "$SCRIPTS/bare_exception_zero_tolerance.py" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS"
axis "R_timeouts = 0" \
  python "$SCRIPTS/timeout_zero_tolerance.py" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS"

axis "All permanent axes are bound" \
  python -m pytest tests/test_python_sole_construction_ci.py -q
axis '`sugar-lift-py-tests[test]` is the sole dependency authority' \
  python -m pytest tests/test_test_extras_are_the_dependency_authority.py -q

# Each law below ships with its discrimination arm: a law whose bad twin also
# passes is not measuring anything.
axis "R_vendor_special_case discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_vendor_special_case_law.py" -q
axis "R_vendor_special_case = 0" python "$SCRIPTS/vendor_special_case_law.py"

axis "R_silent discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_silent_zero_tolerance.py" -q
axis "R_silent = 0" python "$SCRIPTS/silent_zero_tolerance.py"

axis "R_factory_walk_unclassified discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_factory_walk_unclassified_law.py" -q
axis "R_factory_walk_unclassified = 0" \
  python "$SCRIPTS/factory_walk_unclassified_law.py" \
  --live-root "$TESTS/src/sugar_lift_py_tests" \
  --live-root "$SCRIPTS"

axis "R_finite_cap_opaque_completions discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_finite_cap_opaque_completion_law.py" -q
axis "R_finite_cap_opaque_completions = 0" \
  python "$SCRIPTS/finite_cap_opaque_completion_law.py"

axis "R_finite_unfold_compact_gaps discrimination" \
  python -m pytest --noconftest \
  "$TESTS/tests/test_finite_unfold_compact_projection_law.py" -q
axis "R_finite_unfold_compact_gaps = 0" \
  python "$SCRIPTS/finite_unfold_compact_projection_law.py"

axis "R_source_via_execution discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_source_via_execution_law.py" -q
axis "R_source_via_execution = 0" python "$SCRIPTS/source_via_execution_law.py"

axis "R_no_sugar_in_desugar discrimination" \
  python "$SCRIPTS/no_sugar_in_desugar_law.py" --self-test
axis "R_no_sugar_in_desugar = 0" python "$SCRIPTS/no_sugar_in_desugar_law.py"

axis "R_construction_side_doors discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_construction_side_door_law.py" -q
axis "R_construction_side_doors = 0" python "$SCRIPTS/construction_side_door_law.py"

# The bare construction door. SourceFile.from_path builds a tree with no
# construction context; constructing through it does not fail, it LIES --
# every With paints RuntimeSelectedContextManager regardless of resolvability.
# Three false frontiers came out of that door and the defence was a comment.
# The discrimination arm feeds the scanner the actual shape of the probe that
# produced five withdrawn residual pairs -- proved on the incident, not a
# synthetic stand-in.
axis "R_bare_construction_door discrimination" \
  python -m pytest --noconftest \
  "$TESTS/tests/test_construction_context_door_law.py" -q
axis "R_bare_construction_door = 0" \
  python "$SCRIPTS/construction_context_door_law.py"

echo
echo "sole-construction floors: ${#green_axes[@]} green, ${#red_axes[@]} red"
if [ ${#red_axes[@]} -gt 0 ]; then
  echo "RED AXES:"
  printf '  - %s\n' "${red_axes[@]}"
  exit 1
fi
echo "every axis reported, every axis green"
