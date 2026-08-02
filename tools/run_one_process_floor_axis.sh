#!/usr/bin/env bash
# Run exactly one Criterion-2 process floor axis; emit identity-bound report.
#
# Usage: tools/run_one_process_floor_axis.sh <axis_id> <script_name>
#   axis_id: silent | native-crash | bare-exception | timeout
#   script:  silent_zero_tolerance.py | …
#
# Host-durable terminal cache (cross-job): default HOME/.cache/sugar/…
# Workspace-local cache is job-private and would cold-lift every matrix axis.

set -uo pipefail

axis_id="${1:?axis_id}"
script_name="${2:?script}"

TESTS=implementations/python/sugar-lift-py-tests
SCRIPTS="$TESTS/scripts"
SCRIPT="$SCRIPTS/$script_name"

if [ ! -f "$SCRIPT" ]; then
  echo "::error::process floor script missing: $SCRIPT"
  exit 2
fi

PANDAS_CORPUS="$(
  python -c 'from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus; print(authenticated_pandas_corpus().root)'
)" || {
  echo "::error::cannot authenticate pandas corpus for process floor $axis_id"
  exit 1
}

FLOOR_SCRATCH="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}/.sugar/ci-floors/${axis_id}"
export SUGAR_FLOOR_WORKSPACE="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}"

# Cross-job shelf: HOME survives separate matrix jobs on self-hosted runners.
# Workspace paths do not. Override with SUGAR_PROCESS_FLOOR_CACHE_DIR=off to disable.
if [ -z "${SUGAR_PROCESS_FLOOR_CACHE_DIR+x}" ]; then
  export SUGAR_PROCESS_FLOOR_CACHE_DIR="${HOME}/.cache/sugar/process-floor-terminals"
fi
if [ -z "${SUGAR_MEASUREMENT_TIP:-}" ] && [ -n "${GITHUB_SHA:-}" ]; then
  export SUGAR_MEASUREMENT_TIP="${GITHUB_SHA}"
fi

echo "process-floor axis=$axis_id population=$PANDAS_CORPUS"
echo "process-floor cache: dir=${SUGAR_PROCESS_FLOOR_CACHE_DIR} tip=${SUGAR_MEASUREMENT_TIP:-unpinned}"
# Job-log doctrine: unbuffered stdout so phase/count lines hit Actions live.
export PYTHONUNBUFFERED=1
echo "JOB_LOG phase=process-floor-${axis_id} status=start population=$PANDAS_CORPUS"

set +e
python -u "$SCRIPT" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH"
exit_code=$?
set -e
echo "JOB_LOG phase=process-floor-${axis_id} status=end exit_code=$exit_code"

commit="${GITHUB_SHA:-unpinned}"
case "$axis_id" in
  silent) display=R_silent ;;
  native-crash) display=R_native_crashes ;;
  bare-exception) display=R_bare_exceptions ;;
  timeout) display=R_timeouts ;;
  *) display="R_${axis_id}" ;;
esac

python3 tools/sole_construction_floor_enrollment.py \
  --mint-report floor-axis-report.json \
  --axis-id "$axis_id" \
  --display "$display" \
  --kind process \
  --commit-sha "$commit" \
  --exit-code "$exit_code"

exit "$exit_code"
