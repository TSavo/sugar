#!/usr/bin/env bash
set -euo pipefail

# brun_remote_exec.sh — harness test for bin/brun using fake ssh/rsync,
# mirroring tests/bcargo_remote_root_cleanup.sh. Asserts:
#   1. the remote command runs from the caller's repo-relative cwd
#   2. --path-prefix lands in PATH and --env forwards values without provisioning
#   3. repo-root paths in command args are rewritten to the remote root
#   4. the remote exit code propagates
#   5. --sync-back pulls the remote artifact into place after success
#   6. --sync-back also preserves evidence after remote failure without
#      laundering the failure status
#   7. a foreign (ELF) sync-back is refused and deposits nothing

repo_root="${1:-}"
if [[ -z "$repo_root" ]]; then
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [[ -z "$repo_root" ]]; then
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
ssh_log="$tmp/ssh.log"
rsync_log="$tmp/rsync.log"

cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
{
  echo "--- ssh ---"
  for arg in "$@"; do
    printf '<%s>\n' "$arg"
  done
} >>"$BRUN_FAKE_SSH_LOG"
if [[ "${BRUN_FAKE_EXEC_REMOTE:-0}" == "1" ]]; then
  remote_command="${*: -1}"
  remote_status=0
  PATH="$BRUN_FAKE_BIN:$PATH" bash -lc "$remote_command" || remote_status=$?
  # Battleaxe's login-shell logout hook runs clear_console after the generated
  # wrapper and returns 1, replacing both success and nonzero remote verdicts.
  # An exec bridge replaces the login shell before that hook can run.
  if [[ "${BRUN_FAKE_POISON_LOGIN_LOGOUT:-0}" == "1" \
      && "$remote_command" != *"exec \"\$@\""* ]]; then
    exit 1
  fi
  exit "$remote_status"
fi
if [[ "${BRUN_FAKE_CMD_FAIL:-0}" == "1" ]]; then
  for arg in "$@"; do
    case "$arg" in
      *"exec "*)
        exit 23
        ;;
    esac
  done
fi
exit 0
SH
chmod +x "$fake_bin/ssh"

cat >"$fake_bin/flock" <<'SH'
#!/usr/bin/env bash
# The real-shaped local transport arm is serialized by the test process. Its
# job is to execute the generated quiet wrapper, not to re-test util-linux.
exit 0
SH
chmod +x "$fake_bin/flock"

cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
{
  echo "--- rsync ---"
  for arg in "$@"; do
    printf '<%s>\n' "$arg"
  done
} >>"$BRUN_FAKE_RSYNC_LOG"
# Emulate a pull: when the source looks remote (host:path) and the
# destination is a local file path, materialize the destination.
src=""
dest=""
for arg in "$@"; do
  case "$arg" in
    -*) continue ;;
    *) if [[ -z "$src" ]]; then src="$arg"; else dest="$arg"; fi ;;
  esac
done
if [[ "$src" == *:* && -n "$dest" ]]; then
  if [[ "${BRUN_FAKE_PULL_FAIL:-0}" == "1" ]]; then
    exit 29
  fi
  printf '%s' "${BRUN_FAKE_PULL_CONTENT:-remote-artifact}" >"$dest"
fi
exit 0
SH
chmod +x "$fake_bin/rsync"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Exercise the compatibility adapter; all remote policy is owned by sugarbin.
run_brun() {
  (
    cd "$repo_root/implementations/rust"
    PATH="$fake_bin:$PATH" \
    BCARGO_SSH="$fake_bin/ssh" \
    BCARGO_RSYNC="$fake_bin/rsync" \
    BRUN_FAKE_SSH_LOG="$ssh_log" \
    BRUN_FAKE_RSYNC_LOG="$rsync_log" \
    BRUN_FAKE_PULL_CONTENT="${BRUN_FAKE_PULL_CONTENT-}" \
    BRUN_FAKE_PULL_FAIL="${BRUN_FAKE_PULL_FAIL-}" \
    BCARGO_REAP_DAYS=0 \
    "$repo_root/bin/brun" "$@"
  )
}

run_brun_real_shaped_quiet() {
  (
    cd "$repo_root"
    PATH="$fake_bin:$PATH" \
    BCARGO_SSH="$fake_bin/ssh" \
    BCARGO_RSYNC="$fake_bin/rsync" \
    BRUN_FAKE_SSH_LOG="$ssh_log" \
    BRUN_FAKE_RSYNC_LOG="$rsync_log" \
    BRUN_FAKE_BIN="$fake_bin" \
    BRUN_FAKE_EXEC_REMOTE=1 \
    BRUN_FAKE_POISON_LOGIN_LOGOUT=1 \
    BCARGO_REMOTE_ROOT="$tmp/real-shaped-remote" \
    BCARGO_REAP_DAYS=0 \
    SUGAR_BX_REQUIRE_QUIET=1 \
    SUGAR_BX_SKIP_CORPUS_PIN=1 \
    SUGAR_BX_TIMING_LEASE_PATH="$tmp/real-shaped.lease" \
    "$repo_root/bin/brun" "$@"
  )
}

# --- 1-3: cwd, PATH prefix, env forwarding, path rewriting ------------------
: >"$ssh_log"; : >"$rsync_log"
MY_TOKEN="tok-123" run_brun --path-prefix /remote/target/release --env MY_TOKEN \
  -- pytest "$repo_root/implementations/python" >/dev/null

inner="$(grep -F "bash -lc" "$ssh_log" | grep -F "pytest" || true)"
[[ -n "$inner" ]] || fail "no remote exec command logged"
case "$inner" in
  *"/sugar/implementations/rust"*) ;;
  *) fail "remote cwd does not preserve repo-relative dir: $inner" ;;
esac
case "$inner" in
  *"/remote/target/release"*) ;;
  *) fail "--path-prefix missing from remote PATH: $inner" ;;
esac
case "$inner" in
  *"python-kit-env"*|*"PYTHON="*) fail "ambient execution silently provisioned Python: $inner" ;;
esac
case "$inner" in
  *"MY_TOKEN="*"tok-123"*) ;;
  *) fail "--env did not forward MY_TOKEN: $inner" ;;
esac
case "$inner" in
  *"exec "*"pytest"*"/sugar/implementations/python"*) ;;
  *) fail "repo-root arg not rewritten to remote path: $inner" ;;
esac
case "$inner" in
  *"$repo_root"*) fail "local repo root leaked into remote command: $inner" ;;
esac

# --- 4: exit code propagation ------------------------------------------------
: >"$ssh_log"
status=0
BRUN_FAKE_CMD_FAIL=1 run_brun -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 23 ]] || fail "remote exit code not propagated (got $status, want 23)"

# Execute the generated quiet wrapper rather than asking the fake SSH boundary
# to mint an answer. Success and two distinct failures prove status identity;
# a wrapper that collapses every nonzero to 1 cannot satisfy these arms.
status=0
run_brun_real_shaped_quiet -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 0 ]] || fail "real-shaped quiet success collapsed to $status"
for expected in 23 41; do
  status=0
  run_brun_real_shaped_quiet -- bash -lc "exit $expected" \
    >/dev/null 2>&1 || status=$?
  [[ "$status" -eq "$expected" ]] \
    || fail "real-shaped quiet exit $expected collapsed to $status"
done

# --- 5: sync-back pulls the artifact ------------------------------------------
: >"$ssh_log"; : >"$rsync_log"
dest="$tmp/pulled/report.json"
run_brun --sync-back "/remote/out/report.json:$dest" -- true >/dev/null
[[ -f "$dest" ]] || fail "--sync-back did not deposit $dest"
[[ "$(cat "$dest")" == "remote-artifact" ]] || fail "--sync-back deposited wrong content"
grep -Fq "/remote/out/report.json" "$rsync_log" || fail "sync-back pull not logged"

# --- 6: failed remote run still syncs its evidence -----------------------------
: >"$ssh_log"; : >"$rsync_log"
failed_dest="$tmp/pulled/failed-report.json"
status=0
BRUN_FAKE_CMD_FAIL=1 \
  run_brun --sync-back "/remote/out/failed-report.json:$failed_dest" -- true \
  >/dev/null 2>&1 || status=$?
[[ "$status" -eq 23 ]] \
  || fail "sync-back laundered remote failure (got $status, want 23)"
[[ -f "$failed_dest" ]] \
  || fail "remote failure suppressed its evidence sync-back"
[[ "$(cat "$failed_dest")" == "remote-artifact" ]] \
  || fail "failed-run sync-back deposited wrong content"
grep -Fq "/remote/out/failed-report.json" "$rsync_log" \
  || fail "failed-run sync-back pull not logged"

# A transfer failure cannot turn a successful remote command green, and it
# cannot replace a real remote failure with a different verdict. The run
# status is primary; transfer status only closes an otherwise-successful run.
: >"$ssh_log"; : >"$rsync_log"
status=0
BRUN_FAKE_PULL_FAIL=1 \
  run_brun --sync-back "/remote/out/missing.json:$tmp/pulled/missing.json" \
  -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 29 ]] \
  || fail "sync-back failure reported remote success (got $status, want 29)"

: >"$ssh_log"; : >"$rsync_log"
status=0
BRUN_FAKE_CMD_FAIL=1 BRUN_FAKE_PULL_FAIL=1 \
  run_brun --sync-back "/remote/out/failed-missing.json:$tmp/pulled/failed-missing.json" \
  -- true >/dev/null 2>&1 || status=$?
[[ "$status" -eq 23 ]] \
  || fail "sync-back replaced remote failure (got $status, want 23)"
grep -Fq "/remote/out/failed-missing.json" "$rsync_log" \
  || fail "remote failure suppressed attempted sync-back after transfer failure"

# --- 7: foreign ELF sync-back refused -----------------------------------------
if [[ "$(uname -s)" != "Linux" ]]; then
  : >"$ssh_log"; : >"$rsync_log"
  elf_dest="$tmp/pulled/elf-bin"
  elf_content="$(printf '\x7fELF-fake-binary')"
  status=0
  BRUN_FAKE_PULL_CONTENT="$elf_content" \
    run_brun --sync-back "/remote/out/elf-bin:$elf_dest" -- true >/dev/null 2>"$tmp/stderr" || status=$?
  [[ "$status" -eq 0 ]] || fail "foreign sync-back should warn, not fail (got $status)"
  [[ ! -e "$elf_dest" ]] || fail "foreign ELF binary was deposited at $elf_dest"
  grep -q "crime=foreign-platform-binary" "$tmp/stderr" || fail "missing foreign-binary crime line"
fi

echo "PASS: brun remote exec harness"
