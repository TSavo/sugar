#!/usr/bin/env bash
set -euo pipefail

# Live exact-topology tooth. The launching invocation and every observation are
# separate brun/sugarbin processes and therefore separate SSH sessions.
repo_root="${1:-$(git rev-parse --show-toplevel)}"
root="${BCARGO_REMOTE_ROOT:?set BCARGO_REMOTE_ROOT to an explicit disposable battleaxe root}"
job_id="${SUGAR_BX_LIVE_JOB_ID:-axis8-live-$PPID-$$}"
collected="${SUGAR_BX_LIVE_COLLECT_DIR:-$repo_root/.sugar/axis8-live-$job_id}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cd "$repo_root"
BCARGO_REAP_DAYS=0 bin/brun --env docker:core --detach "$job_id" -- \
  bash -lc 'printf "subject-started\n"; sleep 3; printf "subject-complete\n"'

sleep 1
running="$(BCARGO_REAP_DAYS=0 bin/sugarbin job status --host bx --id "$job_id")"
[[ "$running" == *'state=running'* ]] \
  || fail "job did not survive launching SSH disconnect: $running"

sleep 3
completed="$(BCARGO_REAP_DAYS=0 bin/sugarbin job status --host bx --id "$job_id")"
[[ "$completed" == *'state=completed'* && "$completed" == *'exitCode=0'* ]] \
  || fail "job did not preserve successful exit: $completed"

BCARGO_REAP_DAYS=0 bin/sugarbin job collect --host bx --id "$job_id" --output "$collected"
grep -Fq 'subject-started' "$collected/output.log" \
  || fail "collected host log omitted subject start"
grep -Fq 'subject-complete' "$collected/output.log" \
  || fail "collected host log omitted subject completion"
[[ "$(tr -d '[:space:]' <"$collected/exit-code")" == 0 ]] \
  || fail "collected exit identity was not zero"

echo "PASS: battleaxe detached job survived launching SSH disconnect"

