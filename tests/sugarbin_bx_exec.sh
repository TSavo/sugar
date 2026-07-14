#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
ssh_log="$tmp/ssh.log"
rsync_log="$tmp/rsync.log"

cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_SSH_LOG"
for arg in "$@"; do
  case "$arg" in *"exec "*) exit "${BX_FAKE_REMOTE_STATUS:-0}";; esac
done
exit 0
SH
cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_RSYNC_LOG"
src="" dest=""
for arg in "$@"; do
  case "$arg" in -*) continue;; *) [[ -z "$src" ]] && src="$arg" || dest="$arg";; esac
done
if [[ "$src" == *:* && -n "$dest" ]]; then
  printf '%s' "${BX_FAKE_PULL_CONTENT:-remote-artifact}" >"$dest"
fi
SH
cat >"$fake_bin/docker" <<'SH'
#!/usr/bin/env bash
echo docker-invoked >>"$BX_FAKE_DOCKER_LOG"
exit 99
SH
chmod +x "$fake_bin/ssh" "$fake_bin/rsync" "$fake_bin/docker"

fail() { echo "FAIL: $*" >&2; exit 1; }
run_bx() {
  (cd "$repo_root/implementations/rust" &&
    PATH="$fake_bin:$PATH" BCARGO_SSH="$fake_bin/ssh" BCARGO_RSYNC="$fake_bin/rsync" \
    BX_FAKE_SSH_LOG="$ssh_log" BX_FAKE_RSYNC_LOG="$rsync_log" BX_FAKE_DOCKER_LOG="$tmp/docker.log" \
    BCARGO_REMOTE_ROOT="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-broker-test}" \
    "$repo_root/bin/sugarbin" run --host bx --env ambient "$@")
}

: >"$ssh_log"; : >"$rsync_log"; : >"$tmp/docker.log"
status=0
BX_FAKE_REMOTE_STATUS=41 run_bx -- "$repo_root/tools/check.sh" "two words" >/dev/null || status=$?
[[ "$status" -eq 41 ]] || fail "remote exit status was $status, want 41"
[[ "$(grep -c -- '-azR --delete' "$rsync_log")" -eq 1 ]] || fail "workspace must use exactly one rsync"
inner="$(grep -F 'exec ' "$ssh_log" || true)"
[[ "$inner" == *"/sugar/implementations/rust"* ]] || fail "repo-relative cwd not preserved: $inner"
[[ "$inner" == *"/sugar/tools/check.sh"* ]] || fail "repo path not translated: $inner"
[[ "$inner" != *"$repo_root"* ]] || fail "local checkout leaked remotely"
[[ ! -s "$tmp/docker.log" ]] || fail "Docker was invoked"
grep -Fq '.bcargo-tracked-manifest' "$rsync_log" || fail "tracked manifest not synchronized"

# Forwarding controls preserve values containing spaces as single arguments.
: >"$ssh_log"; : >"$rsync_log"
space_dest="$tmp/out with spaces/report.json"
run_bx --path-prefix "/remote/tools with spaces/bin" \
  --sync-back "/remote/out with spaces/report.json:$space_dest" -- true >/dev/null
space_inner="$(grep -F 'exec ' "$ssh_log" || true)"
[[ "$space_inner" == *"/remote/tools with spaces/bin"* ]] || fail "spaced path prefix was split: $space_inner"
grep -Fq '/remote/out with spaces/report.json' "$rsync_log" || fail "spaced sync-back source was split"
[[ -f "$space_dest" ]] || fail "spaced sync-back destination was split"

# cleanup policy: safe roots only; success does not clean failure; always does.
: >"$ssh_log"
status=0
BCARGO_CLEAN_REMOTE_ROOT=always BX_FAKE_REMOTE_STATUS=41 run_bx -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 41 ]] || fail "cleanup changed child status"
grep -Fq "rm -rf '/home/tsavo/remote/sugar-bcargo-broker-test'" "$ssh_log" || fail "always cleanup missing"
: >"$ssh_log"
status=0
BCARGO_CLEAN_REMOTE_ROOT=success BX_FAKE_REMOTE_STATUS=41 run_bx -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 41 ]] || fail "success cleanup changed child status"
! grep -Fq "rm -rf '/home/tsavo/remote/sugar-bcargo-broker-test'" "$ssh_log" || fail "success cleanup ran after failure"
if BCARGO_REMOTE_ROOT=/tmp/unsafe BCARGO_CLEAN_REMOTE_ROOT=success run_bx -- true 2>"$tmp/unsafe.err"; then
  fail "unsafe cleanup root accepted"
fi
grep -Fq 'refusing to clean unsafe remote root' "$tmp/unsafe.err" || fail "unsafe cleanup diagnostic missing"

# stale roots are reaped unless explicitly disabled.
: >"$ssh_log"
BCARGO_REAP_DAYS=3 run_bx -- true >/dev/null
grep -Fq -- "-mtime +'3'" "$ssh_log" || fail "stale root reaping missing"

# sync-back works and refuses foreign ELF on non-Linux callers.
dest="$tmp/out/report.json"
run_bx --sync-back "/remote/report.json:$dest" -- true >/dev/null
[[ "$(cat "$dest")" == remote-artifact ]] || fail "sync-back failed"
if [[ "$(uname -s)" != Linux ]]; then
  elf="$tmp/out/elf"
  BX_FAKE_PULL_CONTENT="$(printf '\177ELF-fake')" run_bx --sync-back "/remote/elf:$elf" -- true 2>"$tmp/elf.err" >/dev/null
  [[ ! -e "$elf" ]] || fail "foreign ELF deposited"
  grep -Fq 'crime=foreign-platform-binary' "$tmp/elf.err" || fail "foreign ELF diagnostic missing"
fi

echo "PASS: sugarbin bx execution contract"
