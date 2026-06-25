#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
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
} >>"$BCARGO_FAKE_SSH_LOG"
if [[ "${BCARGO_FAKE_CARGO_FAIL:-0}" == "1" ]]; then
  for arg in "$@"; do
    case "$arg" in
      *"exec cargo"*)
        exit 17
        ;;
    esac
  done
fi
exit 0
SH

cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BCARGO_FAKE_RSYNC_LOG"
exit 0
SH

chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

run_fake_bcargo() {
  BCARGO_SSH="$fake_bin/ssh" \
  BCARGO_RSYNC="$fake_bin/rsync" \
  BCARGO_FAKE_SSH_LOG="$ssh_log" \
  BCARGO_FAKE_RSYNC_LOG="$rsync_log" \
  BCARGO_PYTHON_ENV=0 \
    "$repo_root/bin/bcargo" check --manifest-path implementations/rust/Cargo.toml
}

default_root="/home/tsavo/remote/sugar-bcargo-clean-contract-default"
: >"$ssh_log"
: >"$rsync_log"
BCARGO_REMOTE_ROOT="$default_root" run_fake_bcargo
if grep -Fq "rm -rf '$default_root'" "$ssh_log"; then
  echo "bcargo cleaned the remote root without BCARGO_CLEAN_REMOTE_ROOT" >&2
  cat "$ssh_log" >&2
  exit 1
fi

clean_root="/home/tsavo/remote/sugar-bcargo-clean-contract"
: >"$ssh_log"
: >"$rsync_log"
BCARGO_REMOTE_ROOT="$clean_root" \
BCARGO_CLEAN_REMOTE_ROOT=success \
  run_fake_bcargo
if ! grep -Fq "rm -rf '$clean_root'" "$ssh_log"; then
  echo "bcargo did not clean a safe remote root after successful cargo" >&2
  cat "$ssh_log" >&2
  exit 1
fi

unsafe_root="/tmp/bcargo-clean-contract"
: >"$ssh_log"
: >"$rsync_log"
if BCARGO_REMOTE_ROOT="$unsafe_root" \
  BCARGO_CLEAN_REMOTE_ROOT=success \
  run_fake_bcargo 2>"$tmp/unsafe.err"
then
  echo "bcargo accepted cleanup for an unsafe remote root" >&2
  cat "$ssh_log" >&2
  exit 1
fi
if ! grep -Fq "refusing to clean unsafe remote root" "$tmp/unsafe.err"; then
  echo "bcargo rejected unsafe cleanup without the expected error" >&2
  cat "$tmp/unsafe.err" >&2
  exit 1
fi

always_root="/home/tsavo/remote/sugar-bcargo-clean-contract-always"
: >"$ssh_log"
: >"$rsync_log"
set +e
BCARGO_REMOTE_ROOT="$always_root" \
BCARGO_CLEAN_REMOTE_ROOT=always \
BCARGO_FAKE_CARGO_FAIL=1 \
  run_fake_bcargo
status=$?
set -e
if [[ "$status" -ne 17 ]]; then
  echo "bcargo did not preserve the remote cargo failure status under cleanup=always" >&2
  echo "status=$status" >&2
  cat "$ssh_log" >&2
  exit 1
fi
if ! grep -Fq "rm -rf '$always_root'" "$ssh_log"; then
  echo "bcargo did not clean a safe remote root after failed cargo with cleanup=always" >&2
  cat "$ssh_log" >&2
  exit 1
fi

success_failure_root="/home/tsavo/remote/sugar-bcargo-clean-contract-success-failure"
: >"$ssh_log"
: >"$rsync_log"
set +e
BCARGO_REMOTE_ROOT="$success_failure_root" \
BCARGO_CLEAN_REMOTE_ROOT=success \
BCARGO_FAKE_CARGO_FAIL=1 \
  run_fake_bcargo
status=$?
set -e
if [[ "$status" -ne 17 ]]; then
  echo "bcargo did not preserve the remote cargo failure status under cleanup=success" >&2
  echo "status=$status" >&2
  cat "$ssh_log" >&2
  exit 1
fi
if grep -Fq "rm -rf '$success_failure_root'" "$ssh_log"; then
  echo "bcargo cleaned the remote root after failed cargo with cleanup=success" >&2
  cat "$ssh_log" >&2
  exit 1
fi
