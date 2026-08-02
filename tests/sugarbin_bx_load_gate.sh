#!/usr/bin/env bash
# Quiet gate: SUGAR_BX_REQUIRE_QUIET / SUGAR_BX_MAX_LOADAVG refuse a busy host
# (exit 76) and do not run the remote command. Opt-in only — unset leaves
# ordinary brun builds ungated.
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
ssh_log="$tmp/ssh.log"
rsync_log="$tmp/rsync.log"
remote_exec_log="$tmp/remote-exec.log"

# Fake ssh:
# - load-sample commands (contain /proc/loadavg or getloadavg) print BX_FAKE_LOAD
# - ambient run is bash -lc '… exec …' (must NOT match find -exec reaper)
cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_SSH_LOG"
joined="$*"
case "$joined" in
  *'/proc/loadavg'*|*'getloadavg'*)
    # "load1 nproc"
    printf '%s\n' "${BX_FAKE_LOAD:-0.50 32}"
    exit 0
    ;;
esac
# Ambient command is sugar_bx_run_ambient: bash -lc 'cd … && exec …'
# The reaper uses find -exec — do not treat that as the measured command.
if [[ "$joined" == *'bash -lc'* && "$joined" == *' exec '* ]]; then
  printf '%s\n' "$joined" >>"$BX_FAKE_REMOTE_EXEC_LOG"
  exit "${BX_FAKE_REMOTE_STATUS:-0}"
fi
exit 0
SH
cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

fail() { echo "FAIL: $*" >&2; exit 1; }

run_bx() {
  (cd "$repo_root" &&
    PATH="$fake_bin:$PATH" BCARGO_SSH="$fake_bin/ssh" BCARGO_RSYNC="$fake_bin/rsync" \
    BX_FAKE_SSH_LOG="$ssh_log" BX_FAKE_RSYNC_LOG="$rsync_log" \
    BX_FAKE_REMOTE_EXEC_LOG="$remote_exec_log" \
    BCARGO_REMOTE_ROOT="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-load-gate-test}" \
    BCARGO_FORCE_REMOTE=1 \
    "$repo_root/bin/sugarbin" run --host bx --env ambient "$@")
}

# 1) Gate off by default: busy load must NOT refuse, and command must run.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="20.0 32"
status=0
run_bx -- true >/dev/null 2>"$tmp/stderr1" || status=$?
[[ "$status" -eq 0 ]] || fail "ungated run failed status=$status (want 0)"
[[ -s "$remote_exec_log" ]] || fail "ungated run never reached remote exec"
grep -q 'bx-load-gate' "$tmp/stderr1" && fail "ungated run printed load gate noise" || true

# 2) REQUIRE_QUIET=1 + busy load → exit 76, no remote exec.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="20.0 32"
status=0
SUGAR_BX_REQUIRE_QUIET=1 run_bx -- true >/dev/null 2>"$tmp/stderr2" || status=$?
[[ "$status" -eq 76 ]] || fail "busy host status=$status want 76"
[[ ! -s "$remote_exec_log" ]] || fail "busy host still ran remote command"
grep -Fq 'crime=host-not-quiet' "$tmp/stderr2" || fail "missing host-not-quiet crime line"
grep -Fq 'phase=before' "$tmp/stderr2" || fail "missing before load line"

# 3) REQUIRE_QUIET=1 + quiet load → runs, prints before+after.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="2.05 32"
status=0
SUGAR_BX_REQUIRE_QUIET=1 run_bx -- true >/dev/null 2>"$tmp/stderr3" || status=$?
[[ "$status" -eq 0 ]] || fail "quiet host status=$status want 0"
[[ -s "$remote_exec_log" ]] || fail "quiet host never reached remote exec"
grep -Fq 'phase=before' "$tmp/stderr3" || fail "quiet run missing before"
grep -Fq 'phase=after' "$tmp/stderr3" || fail "quiet run missing after"

# 4) Explicit MAX_LOADAVG alone arms the gate; load just under passes.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="7.9 32"
status=0
SUGAR_BX_MAX_LOADAVG=8 run_bx -- true >/dev/null 2>"$tmp/stderr4" || status=$?
[[ "$status" -eq 0 ]] || fail "max-load under ceiling status=$status want 0"

# 5) Explicit MAX_LOADAVG: load just over refuses.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="8.01 32"
status=0
SUGAR_BX_MAX_LOADAVG=8 run_bx -- true >/dev/null 2>"$tmp/stderr5" || status=$?
[[ "$status" -eq 76 ]] || fail "max-load over ceiling status=$status want 76"
[[ ! -s "$remote_exec_log" ]] || fail "over-ceiling still ran remote command"

# 6) brun adapter surfaces the same env (wrapper only; exercise via sugarbin path above).
grep -Fq 'SUGAR_BX_REQUIRE_QUIET' "$repo_root/bin/brun" || fail "brun --help text missing quiet gate"
grep -Fq 'SUGAR_BX_REQUIRE_QUIET' "$repo_root/bin/lib/sugar-bx.sh" || fail "sugar-bx missing require_quiet"
test -f "$repo_root/docs/contributing/battleaxe-timing.md" || fail "canonical timing doc missing"

echo "PASS: sugarbin_bx_load_gate"
