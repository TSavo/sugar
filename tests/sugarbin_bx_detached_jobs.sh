#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/systemd" "$tmp/remote-root"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cat >"$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${FAKE_SYSTEMD_AVAILABLE:-1}" == 1 ]] || exit 1
unit=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --unit=*) unit="${1#*=}"; shift ;;
    --unit) unit="$2"; shift 2 ;;
    --property=*|--collect|--user|--quiet) shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[[ -n "$unit" && $# -gt 0 ]]
nohup "$@" </dev/null >/dev/null 2>&1 &
printf '%s\n' "$!" >"$FAKE_SYSTEMD_STATE/$unit.pid"
SH

cat >"$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${FAKE_SYSTEMD_AVAILABLE:-1}" == 1 ]] || exit 1
[[ "${1:-}" == --user ]] && shift
case "${1:-}" in
  show-environment) exit 0 ;;
  is-active)
    unit="${2:?unit}"
    pid_file="$FAKE_SYSTEMD_STATE/$unit.pid"
    [[ -r "$pid_file" ]] || exit 3
    pid="$(cat "$pid_file")"
    kill -0 "$pid" 2>/dev/null
    ;;
  *) exit 1 ;;
esac
SH

cat >"$tmp/bin/loginctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${FAKE_LINGER_ENABLED:-1}" == 1 ]] && printf 'yes\n' || printf 'no\n'
SH
chmod +x "$tmp/bin/systemd-run" "$tmp/bin/systemctl" "$tmp/bin/loginctl"

# shellcheck source=bin/lib/sugar-bx.sh
source "$repo_root/bin/lib/sugar-bx.sh"

# A separate shell per call models separate SSH sessions while retaining only
# host-owned files and the user-systemd unit between them.
sugar_bx_ssh() {
  bash -c "$*"
}

export PATH="$tmp/bin:$PATH"
export FAKE_SYSTEMD_STATE="$tmp/systemd"
export FAKE_SYSTEMD_AVAILABLE=1
export FAKE_LINGER_ENABLED=1
export USER="${USER:-tester}"
SUGAR_BX_HOST=fake-battleaxe
SUGAR_BX_LOCAL=0
SUGAR_BX_ROOT="$tmp/remote-root"
SUGAR_BX_CLEAN=never

start_ns="$(python3 -c 'import time; print(time.monotonic_ns())')"
sugar_bx_start_detached_host_command axis8-ok \
  "sleep 0.5; printf 'subject-complete\\n'"
end_ns="$(python3 -c 'import time; print(time.monotonic_ns())')"
elapsed_ms="$(( (end_ns - start_ns) / 1000000 ))"
[[ "$elapsed_ms" -lt 400 ]] \
  || fail "launch waited for the subject instead of returning ownership: ${elapsed_ms}ms"

# The launching session has returned. A distinct shell must see the job active
# and its host-owned log readable while the subject is still running.
sleep 0.1
running="$(sugar_bx_detached_job_status axis8-ok)"
[[ "$running" == *'state=running'* ]] || fail "second session did not see running job: $running"
[[ -r "$SUGAR_BX_ROOT/.sugar-bx-jobs/axis8-ok/output.log" ]] \
  || fail "host-owned log was not readable after launch session returned"

sleep 0.6
completed="$(sugar_bx_detached_job_status axis8-ok)"
[[ "$completed" == *'state=completed'* && "$completed" == *'exitCode=0'* ]] \
  || fail "successful final status was not durable: $completed"
grep -Fq 'subject-complete' "$SUGAR_BX_ROOT/.sugar-bx-jobs/axis8-ok/output.log" \
  || fail "successful subject output was not durable"

sugar_bx_collect_detached_job axis8-ok "$tmp/collected-ok"
cmp "$SUGAR_BX_ROOT/.sugar-bx-jobs/axis8-ok/output.log" "$tmp/collected-ok/output.log" \
  || fail "collect changed durable output bytes"
cmp "$SUGAR_BX_ROOT/.sugar-bx-jobs/axis8-ok/exit-code" "$tmp/collected-ok/exit-code" \
  || fail "collect changed durable exit identity"

# A failed detached subject must remain a failed measurement. The protocol
# records 23 exactly rather than converting it into launch success or silence.
sugar_bx_start_detached_host_command axis8-fail "printf 'failed-subject\\n'; exit 23"
for _ in 1 2 3 4 5; do
  [[ -r "$SUGAR_BX_ROOT/.sugar-bx-jobs/axis8-fail/exit-code" ]] && break
  sleep 0.1
done
failed="$(sugar_bx_detached_job_status axis8-fail)"
[[ "$failed" == *'state=completed'* && "$failed" == *'exitCode=23'* ]] \
  || fail "nonzero subject exit was not preserved: $failed"

status=0
sugar_bx_start_detached_host_command '../bad' true >"$tmp/invalid.out" 2>"$tmp/invalid.err" || status=$?
[[ "$status" == 70 ]] || fail "invalid job id returned $status, want 70"
grep -Fq 'crime=invalid-detached-job-id' "$tmp/invalid.err" \
  || fail "invalid job id refusal was unnamed"

status=0
sugar_bx_start_detached_host_command axis8-ok true >"$tmp/duplicate.out" 2>"$tmp/duplicate.err" || status=$?
[[ "$status" == 70 ]] || fail "duplicate job id returned $status, want 70"
grep -Fq 'crime=duplicate-detached-job-id' "$tmp/duplicate.err" \
  || fail "duplicate job id refusal was unnamed"

status=0
FAKE_SYSTEMD_AVAILABLE=0 sugar_bx_start_detached_host_command axis8-no-systemd true \
  >"$tmp/systemd.out" 2>"$tmp/systemd.err" || status=$?
[[ "$status" == 70 ]] || fail "unavailable systemd returned $status, want 70"
grep -Fq 'crime=detached-supervisor-unavailable' "$tmp/systemd.err" \
  || fail "unavailable systemd refusal was unnamed"

status=0
FAKE_LINGER_ENABLED=0 sugar_bx_start_detached_host_command axis8-no-linger true \
  >"$tmp/linger.out" 2>"$tmp/linger.err" || status=$?
[[ "$status" == 70 ]] || fail "disabled linger returned $status, want 70"
grep -Fq 'crime=detached-linger-disabled' "$tmp/linger.err" \
  || fail "disabled linger refusal was unnamed"

status=0
SUGAR_BX_CLEAN=success sugar_bx_start_detached_host_command axis8-clean true \
  >"$tmp/clean.out" 2>"$tmp/clean.err" || status=$?
[[ "$status" == 70 ]] || fail "cleanup conflict returned $status, want 70"
grep -Fq 'crime=detached-cleanup-policy-conflict' "$tmp/clean.err" \
  || fail "cleanup conflict refusal was unnamed"

echo "PASS: sugarbin battleaxe detached-job contract"

