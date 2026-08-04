#!/usr/bin/env bash
set -euo pipefail

# Live exact-topology tooth. The launching invocation and every observation are
# separate brun/sugarbin processes and therefore separate SSH sessions.
repo_root="${1:-$(git rev-parse --show-toplevel)}"
root="${BCARGO_REMOTE_ROOT:?set BCARGO_REMOTE_ROOT to an explicit disposable battleaxe root}"
job_id="${SUGAR_BX_LIVE_JOB_ID:-axis8-live-$PPID-$$}"
collected="${SUGAR_BX_LIVE_COLLECT_DIR:-$repo_root/.sugar/axis8-live-$job_id}"
failed_job_id="$job_id-fail"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

wait_for_completed_status() {
  local wanted_job_id="$1" observation="" attempt
  for attempt in $(seq 1 60); do
    observation="$(BCARGO_REAP_DAYS=0 bin/sugarbin job status --host bx --id "$wanted_job_id")"
    case "$observation" in
      *'state=completed'*) printf '%s\n' "$observation"; return 0 ;;
      *'state=running'*) sleep 1 ;;
      *) fail "unexpected detached status for $wanted_job_id: $observation" ;;
    esac
  done
  fail "detached job did not complete inside 60s: $observation"
}

cd "$repo_root"
BCARGO_REAP_DAYS=0 bin/brun --env docker:core --detach "$job_id" -- \
  bash -lc 'printf "subject-started\n"; sleep 3; printf "subject-complete\n"'

sleep 1
running="$(BCARGO_REAP_DAYS=0 bin/sugarbin job status --host bx --id "$job_id")"
[[ "$running" == *'state=running'* ]] \
  || fail "job did not survive launching SSH disconnect: $running"

completed="$(wait_for_completed_status "$job_id")"
[[ "$completed" == *'state=completed'* && "$completed" == *'exitCode=0'* ]] \
  || fail "job did not preserve successful exit: $completed"

BCARGO_REAP_DAYS=0 bin/sugarbin job collect --host bx --id "$job_id" --output "$collected"
grep -Fq 'subject-started' "$collected/output.log" \
  || fail "collected host log omitted subject start"
grep -Fq 'subject-complete' "$collected/output.log" \
  || fail "collected host log omitted subject completion"
[[ "$(tr -d '[:space:]' <"$collected/exit-code")" == 0 ]] \
  || fail "collected exit identity was not zero"

# The launcher succeeding is not the subject succeeding. A second live job
# proves a nonzero subject verdict remains exactly nonzero after disconnect,
# status, and collection.
BCARGO_REAP_DAYS=0 bin/brun --env docker:core --detach "$failed_job_id" -- \
  bash -lc 'printf "failed-subject\n"; exit 23'
failed="$(wait_for_completed_status "$failed_job_id")"
[[ "$failed" == *'exitCode=23'* ]] \
  || fail "failed job did not preserve exit 23: $failed"
BCARGO_REAP_DAYS=0 bin/sugarbin job collect --host bx --id "$failed_job_id" \
  --output "$collected-fail"
[[ "$(tr -d '[:space:]' <"$collected-fail/exit-code")" == 23 ]] \
  || fail "collected failed exit identity was not 23"
grep -Fq 'failed-subject' "$collected-fail/output.log" \
  || fail "collected failed log omitted subject testimony"

echo "PASS: battleaxe detached jobs survived disconnect and preserved exit 0/23"
