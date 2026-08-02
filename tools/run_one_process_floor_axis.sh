#!/usr/bin/env bash
# Run exactly one Criterion-2 process floor axis file-shard; emit identity-bound report.
#
# Usage: tools/run_one_process_floor_axis.sh <axis_base> <script_name> <shard_index> <shard_count>
#   axis_base: silent | native-crash | bare-exception | timeout
#   seat id minted as ${axis_base}-s${shard_index:02d}
#
# Exit vocabulary (enrollment mint):
#   0 — scan completed, residual green
#   1 — scan completed, residual red
#   2+ — scan did not complete (auth/init/crash) → report UNMEASURED

set -uo pipefail

axis_base="${1:?axis_base}"
script_name="${2:?script}"
shard_index="${3:?shard_index}"
shard_count="${4:?shard_count}"

axis_seat="$(printf '%s-s%02d' "$axis_base" "$shard_index")"

TESTS=implementations/python/sugar-lift-py-tests
SCRIPTS="$TESTS/scripts"
SCRIPT="$SCRIPTS/$script_name"

if [ ! -f "$SCRIPT" ]; then
  echo "::error::process floor script missing: $SCRIPT"
  exit 2
fi

# LPT prior shelf — content-addressed; fleet-shared via actions/cache.
if [ -z "${SUGAR_LPT_PRIOR_DIR+x}" ]; then
  if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    export SUGAR_LPT_PRIOR_DIR="${GITHUB_WORKSPACE}/.cache/sugar/lpt-file-costs"
  else
    export SUGAR_LPT_PRIOR_DIR="${HOME}/.cache/sugar/lpt-file-costs"
  fi
fi
mkdir -p "${SUGAR_LPT_PRIOR_DIR}" 2>/dev/null || true

PANDAS_CORPUS="$(
  python -c 'from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus; print(authenticated_pandas_corpus().root)'
)" || {
  echo "::error::cannot authenticate pandas corpus for process floor $axis_seat"
  commit="${GITHUB_SHA:-unpinned}"
  case "$axis_base" in
    silent) display="R_silent[s$(printf '%02d' "$shard_index")]" ;;
    native-crash) display="R_native_crashes[s$(printf '%02d' "$shard_index")]" ;;
    bare-exception) display="R_bare_exceptions[s$(printf '%02d' "$shard_index")]" ;;
    timeout) display="R_timeouts[s$(printf '%02d' "$shard_index")]" ;;
    *) display="R_${axis_base}[s$(printf '%02d' "$shard_index")]" ;;
  esac
  python3 tools/sole_construction_floor_enrollment.py \
    --mint-report floor-axis-report.json \
    --axis-id "$axis_seat" \
    --display "$display" \
    --kind process \
    --commit-sha "$commit" \
    --exit-code 2 \
    --no-scan-completed \
    --unmeasured-reason "authenticated pandas corpus auth/init failed"
  exit 2
}

FLOOR_SCRATCH="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}/.sugar/ci-floors/${axis_seat}"
export SUGAR_FLOOR_WORKSPACE="${SUGAR_FLOOR_WORKSPACE:-${GITHUB_WORKSPACE:-${RUNNER_TEMP:-$(pwd)}}}"

if [ -z "${SUGAR_PROCESS_FLOOR_CACHE_DIR+x}" ]; then
  if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    export SUGAR_PROCESS_FLOOR_CACHE_DIR="${GITHUB_WORKSPACE}/.cache/sugar/process-floor-terminals"
  else
    export SUGAR_PROCESS_FLOOR_CACHE_DIR="${HOME}/.cache/sugar/process-floor-terminals"
  fi
fi
if [ -z "${SUGAR_MEASUREMENT_TIP:-}" ] && [ -n "${GITHUB_SHA:-}" ]; then
  export SUGAR_MEASUREMENT_TIP="${GITHUB_SHA}"
fi

echo "process-floor seat=$axis_seat population=$PANDAS_CORPUS shard=$shard_index/$shard_count"
echo "process-floor cache: dir=${SUGAR_PROCESS_FLOOR_CACHE_DIR} tip=${SUGAR_MEASUREMENT_TIP:-unpinned}"
echo "process-floor lpt_prior: dir=${SUGAR_LPT_PRIOR_DIR}"
export PYTHONUNBUFFERED=1
echo "JOB_LOG phase=process-floor-${axis_seat} status=start population=$PANDAS_CORPUS"

set +e
python -u "$SCRIPT" "$PANDAS_CORPUS" \
  --repo-root "$PANDAS_CORPUS" \
  --out-dir "$FLOOR_SCRATCH" \
  --shard-index "$shard_index" \
  --shard-count "$shard_count"
exit_code=$?
set -e
echo "JOB_LOG phase=process-floor-${axis_seat} status=end exit_code=$exit_code"

commit="${GITHUB_SHA:-unpinned}"
case "$axis_base" in
  silent) display="R_silent[s$(printf '%02d' "$shard_index")]" ;;
  native-crash) display="R_native_crashes[s$(printf '%02d' "$shard_index")]" ;;
  bare-exception) display="R_bare_exceptions[s$(printf '%02d' "$shard_index")]" ;;
  timeout) display="R_timeouts[s$(printf '%02d' "$shard_index")]" ;;
  *) display="R_${axis_base}[s$(printf '%02d' "$shard_index")]" ;;
esac

mint_args=(
  --mint-report floor-axis-report.json
  --axis-id "$axis_seat"
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
