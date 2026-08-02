#!/usr/bin/env bash
# Cheap static / discrimination sole-construction floors — own parallel job.
# Must not wait on process-floor matrix (silent ~11min). Collect reds; exit 1 if any.

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
    echo "$name: GREEN (measurement completed)"
  else
    local status=$?
    red_axes+=("$name (exit $status)")
    echo "::error::$name is RED (exit $status)"
  fi
  echo "::endgroup::"
}

axis "R_ownership = 0" python "$SCRIPTS/factory_ownership_law.py"
axis "R_construction_panic_catches_outside_membrane = 0" \
  python "$SCRIPTS/construction_panic_catch_law.py"

axis "All permanent axes are bound" \
  python -m pytest tests/test_python_sole_construction_ci.py -q
axis '`sugar-lift-py-tests[test]` is the sole dependency authority' \
  python -m pytest tests/test_test_extras_are_the_dependency_authority.py -q

axis "R_vendor_special_case discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_vendor_special_case_law.py" -q
axis "R_vendor_special_case = 0" python "$SCRIPTS/vendor_special_case_law.py"

axis "R_silent discrimination" \
  python -m pytest --noconftest "$TESTS/tests/test_silent_zero_tolerance.py" -q

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

axis "R_bare_construction_door discrimination" \
  python -m pytest --noconftest \
  "$TESTS/tests/test_construction_context_door_law.py" -q
axis "R_bare_construction_door = 0" \
  python "$SCRIPTS/construction_context_door_law.py"

echo
echo "static sole-construction floors: ${#green_axes[@]} green, ${#red_axes[@]} red"
if [ ${#red_axes[@]} -gt 0 ]; then
  echo "RED AXES:"
  printf '  - %s\n' "${red_axes[@]}"
  exit 1
fi
echo "every static axis reported, every axis green"
exit 0
