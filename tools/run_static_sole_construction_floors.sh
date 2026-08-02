#!/usr/bin/env bash
# Cheap static / discrimination sole-construction floors — own parallel job.
# Must not wait on process-floor matrix (silent ~11min). Collect reds; exit 1 if any.
#
# SILENCE CONCEALS: named phases + index/total + unbuffered python so a stall
# names which discrimination is live (not one fused black box).

set -uo pipefail
export PYTHONUNBUFFERED=1

TESTS=implementations/python/sugar-lift-py-tests
SCRIPTS="$TESTS/scripts"

red_axes=()
green_axes=()
all_axes=()
axis_index=0
# Count axis() invocations for progress (updated as axes are declared below).
AXIS_TOTAL=22

axis() {
  local name="$1"; shift
  all_axes+=("$name")
  axis_index=$((axis_index + 1))
  echo "static_floors phase=axis index=${axis_index}/${AXIS_TOTAL} name=${name} status=start"
  echo "::group::[${axis_index}/${AXIS_TOTAL}] $name"
  if "$@"; then
    green_axes+=("$name")
    echo "$name: GREEN (measurement completed)"
    echo "static_floors phase=axis index=${axis_index}/${AXIS_TOTAL} name=${name} status=green running_green=${#green_axes[@]} running_red=${#red_axes[@]}"
  else
    local status=$?
    red_axes+=("$name")
    echo "::error::$name is RED (exit $status)"
    echo "static_floors phase=axis index=${axis_index}/${AXIS_TOTAL} name=${name} status=red exit=${status} running_green=${#green_axes[@]} running_red=${#red_axes[@]}"
  fi
  echo "::endgroup::"
}

echo "static_floors phase=begin axis_total=${AXIS_TOTAL}"

axis "R_ownership = 0" python -u "$SCRIPTS/factory_ownership_law.py"
axis "R_construction_panic_catches_outside_membrane = 0" \
  python -u "$SCRIPTS/construction_panic_catch_law.py"

axis "All permanent axes are bound" \
  python -u -m pytest tests/test_python_sole_construction_ci.py -v --tb=line
axis '`sugar-lift-py-tests[test]` is the sole dependency authority' \
  python -u -m pytest tests/test_test_extras_are_the_dependency_authority.py -v --tb=line

axis "R_vendor_special_case discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_vendor_special_case_law.py" -v --tb=line
axis "R_vendor_special_case = 0" python -u "$SCRIPTS/vendor_special_case_law.py"

axis "R_silent discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_silent_zero_tolerance.py" -v --tb=line

axis "R_factory_walk_unclassified discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_factory_walk_unclassified_law.py" -v --tb=line
axis "R_factory_walk_unclassified = 0" \
  python -u "$SCRIPTS/factory_walk_unclassified_law.py" \
  --live-root "$TESTS/src/sugar_lift_py_tests" \
  --live-root "$SCRIPTS"

axis "R_finite_cap_opaque_completions discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_finite_cap_opaque_completion_law.py" -v --tb=line
axis "R_finite_cap_opaque_completions = 0" \
  python -u "$SCRIPTS/finite_cap_opaque_completion_law.py"

axis "R_finite_unfold_compact_gaps discrimination" \
  python -u -m pytest --noconftest \
  "$TESTS/tests/test_finite_unfold_compact_projection_law.py" -v --tb=line
axis "R_finite_unfold_compact_gaps = 0" \
  python -u "$SCRIPTS/finite_unfold_compact_projection_law.py"

axis "R_source_via_execution discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_source_via_execution_law.py" -v --tb=line
axis "R_source_via_execution = 0" python -u "$SCRIPTS/source_via_execution_law.py"

axis "R_no_sugar_in_desugar discrimination" \
  python -u "$SCRIPTS/no_sugar_in_desugar_law.py" --self-test
axis "R_no_sugar_in_desugar = 0" python -u "$SCRIPTS/no_sugar_in_desugar_law.py"

axis "R_construction_side_doors discrimination" \
  python -u -m pytest --noconftest "$TESTS/tests/test_construction_side_door_law.py" -v --tb=line
axis "R_construction_side_doors = 0" python -u "$SCRIPTS/construction_side_door_law.py"

axis "R_bare_construction_door discrimination" \
  python -u -m pytest --noconftest \
  "$TESTS/tests/test_construction_context_door_law.py" -v --tb=line
axis "R_bare_construction_door = 0" \
  python -u "$SCRIPTS/construction_context_door_law.py"

# Fifth hierarchy-lie class: construction extends the graph; consuming doors
# lag the closed codomain → TypeError erases file rosters. Static, seconds,
# no corpus. Enrollment is existence — not a one-shot audit.
axis "R_construction_consumer_codomain discrimination" \
  python -u "$SCRIPTS/construction_consumer_codomain_law.py" --self-test
axis "R_construction_consumer_codomain = 0" \
  python -u "$SCRIPTS/construction_consumer_codomain_law.py"

echo
echo "static_floors phase=end green=${#green_axes[@]} red=${#red_axes[@]}"
echo "static sole-construction floors: ${#green_axes[@]} green, ${#red_axes[@]} red"
# Residual magnitude for enrollment mint — count of red static axes, not exit invent.
residual_json="${SUGAR_STATIC_FLOOR_RESIDUAL_JSON:-floor-static-residual.json}"
mint_args=(--out "$residual_json")
for name in "${all_axes[@]}"; do mint_args+=(--input-axis "$name"); done
for name in "${green_axes[@]}"; do mint_args+=(--green-axis "$name"); done
for name in "${red_axes[@]}"; do mint_args+=(--red-axis "$name"); done
if ! python3 -u tools/static_floor_residual_report.py "${mint_args[@]}"; then
  echo "::error::static floor conservation refused; residual is UNMEASURED"
  exit 2
fi
if [ ${#red_axes[@]} -gt 0 ]; then
  echo "RED AXES:"
  printf '  - %s\n' "${red_axes[@]}"
  exit 1
fi
echo "every static axis reported, every axis green"
exit 0
