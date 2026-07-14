#!/usr/bin/env bash
set -euo pipefail

# brun_remote_exec.sh — harness test for bin/brun using fake ssh/rsync,
# mirroring tests/bcargo_remote_root_cleanup.sh. Asserts:
#   1. the remote command runs from the caller's repo-relative cwd
#   2. --path-prefix lands in PATH and --env forwards values without provisioning
#   3. repo-root paths in command args are rewritten to the remote root
#   4. the remote exit code propagates
#   5. --sync-back pulls the remote artifact into place
#   6. a foreign (ELF) sync-back is refused and deposits nothing

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
    BCARGO_REAP_DAYS=0 \
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

# --- 5: sync-back pulls the artifact ------------------------------------------
: >"$ssh_log"; : >"$rsync_log"
dest="$tmp/pulled/report.json"
run_brun --sync-back "/remote/out/report.json:$dest" -- true >/dev/null
[[ -f "$dest" ]] || fail "--sync-back did not deposit $dest"
[[ "$(cat "$dest")" == "remote-artifact" ]] || fail "--sync-back deposited wrong content"
grep -Fq "/remote/out/report.json" "$rsync_log" || fail "sync-back pull not logged"

# --- 6: foreign ELF sync-back refused -----------------------------------------
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
