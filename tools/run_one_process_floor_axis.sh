#!/usr/bin/env bash
# Run exactly one Criterion-2 process floor axis; emit identity-bound report.
#
# Usage: tools/run_one_process_floor_axis.sh <axis_id> <script_name>
#
# Exit vocabulary (enrollment mint):
#   0 — scan completed, residual green
#   1 — scan completed, residual red
#   2+ — scan did not complete (auth/init/crash) → report UNMEASURED

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
  # Auth failure is infrastructure UNMEASURED, not residual red.
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
    --exit-code 2 \
    --no-scan-completed \
    --unmeasured-reason "authenticated pandas corpus auth/init failed"
  exit 2
}

FLOOR_SCRATCH="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}/.sugar/ci-floors/${axis_id}"
export SUGAR_FLOOR_WORKSPACE="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}"

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

# 0/1 = scan completed (green/red residual); >=2 = infrastructure UNMEASURED
mint_args=(
  --mint-report floor-axis-report.json
  --axis-id "$axis_id"
  --display "$display"
  --kind process
  --commit-sha "$commit"
  --exit-code "$exit_code"
)
if [ "$exit_code" -ge 2 ]; then
  mint_args+=(--no-scan-completed --unmeasured-reason "process floor exit=${exit_code} (auth/init/bootstrap/crash — not residual)")
fi

python3 tools/sole_construction_floor_enrollment.py "${mint_args[@]}"

exit "$exit_code"
