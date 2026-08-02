#!/usr/bin/env bash
# LOCAL / serial convenience: run the full sole-construction floor set in-process.
#
# CI is parallel: .github/workflows/factory-zero-tolerance.yml runs each process
# axis as its own job + a static-laws job, with enrollment roll call. Prefer
# that on push. This script remains for workstation re-runs and binding checks.
#
# `if: always()` semantics: EVERY axis runs, failures collected, exit non-zero
# if any axis was red. R > 0 ⇒ red on every residual axis.
#
# Usage: tools/run_sole_construction_floors.sh   (from the repo root)

set -uo pipefail

TESTS=implementations/python/sugar-lift-py-tests
SCRIPTS="$TESTS/scripts"

red_axes=()
green_axes=()

axis() {
  local name="$1"; shift
  # Axis names must NOT embed "= 0". A pre-measure crash still paints the group
  # header; embedding a zero there banks a number that was never taken (S0.2).
  echo "::group::$name"
  if "$@"; then
    green_axes+=("$name")
    echo "$name: GREEN (measurement completed)"
  else
    local status=$?
    red_axes+=("$name (exit $status)")
    echo "::error::$name is RED (exit $status). If the body printed unmeasured/no-value, residual is not a completed zero."
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
DEMAND_TABLE_PATH="${DEMAND_TABLE_PATH:-}"
if [ -z "$DEMAND_TABLE_PATH" ] || [ ! -s "$DEMAND_TABLE_PATH" ]; then
  echo "::error::authenticated python-demand-table required for process floors; set DEMAND_TABLE_PATH to the pulled table"
  exit 2
fi
echo "process-floor demand table: $DEMAND_TABLE_PATH"
# --repo-root is the population (relative loci). Scratch must NOT nest under it
# (vendor site-packages is read-only; mutating the population is wrong even when
# mkdir succeeds). Workspace/tmp only — same vocabulary as prepare_floor_io.
FLOOR_SCRATCH="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}/.sugar/ci-floors"
export SUGAR_FLOOR_WORKSPACE="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}"
echo "process-floor scratch: $FLOOR_SCRATCH (never under population)"
# Content-addressed process-floor terminal shelf (#7009):
# tip × corpusManifestCid × axis × fileContentCid × demandTableCid × fileTimeoutMs
# Host-durable default so serial local runs and parallel CI jobs share hits.
# Disable: SUGAR_PROCESS_FLOOR_CACHE_DIR=off
if [ -z "${SUGAR_PROCESS_FLOOR_CACHE_DIR+x}" ]; then
  export SUGAR_PROCESS_FLOOR_CACHE_DIR="${HOME}/.cache/sugar/process-floor-terminals"
fi
if [ -z "${SUGAR_MEASUREMENT_TIP:-}" ] && [ -n "${GITHUB_SHA:-}" ]; then
  export SUGAR_MEASUREMENT_TIP="${GITHUB_SHA}"
fi
echo "process-floor cache: dir=${SUGAR_PROCESS_FLOOR_CACHE_DIR} tip=${SUGAR_MEASUREMENT_TIP:-unpinned}"
# Axis names: R_axis only — never "R_axis = 0" (false banked zero on pre-measure crash).
axis "R_native_crashes" \
  python "$SCRIPTS/native_crash_zero_tolerance.py" "$PANDAS_CORPUS" \
  --demand-table-path "$DEMAND_TABLE_PATH" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH/native-crash"
axis "R_bare_exceptions" \
  python "$SCRIPTS/bare_exception_zero_tolerance.py" "$PANDAS_CORPUS" \
  --demand-table-path "$DEMAND_TABLE_PATH" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH/bare-exception"
axis "R_timeouts" \
  python "$SCRIPTS/timeout_zero_tolerance.py" "$PANDAS_CORPUS" \
  --demand-table-path "$DEMAND_TABLE_PATH" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH/timeout"
# R_silent is Criterion 2's fourth simultaneous term — same population as the
# three process floors. Kit-default silent was a false green (unmeasured corpus).
axis "R_silent" \
  python "$SCRIPTS/silent_zero_tolerance.py" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH/silent"

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
# Live R_silent over corpus is bound with the process floors above (PANDAS_CORPUS).
# Do not re-invoke with kit defaults — that is the wrong-population door.

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

# Fifth hierarchy-lie class (static, seconds). See construction_consumer_codomain_law.py.
axis "R_construction_consumer_codomain discrimination" \
  python "$SCRIPTS/construction_consumer_codomain_law.py" --self-test
axis "R_construction_consumer_codomain = 0" \
  python "$SCRIPTS/construction_consumer_codomain_law.py"

echo
echo "sole-construction floors: ${#green_axes[@]} green, ${#red_axes[@]} red"
if [ ${#red_axes[@]} -gt 0 ]; then
  echo "RED AXES:"
  printf '  - %s\n' "${red_axes[@]}"
  exit 1
fi
echo "every axis reported, every axis green"
