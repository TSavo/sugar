#!/usr/bin/env bash
set -euo pipefail

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
last=""
for arg in "$@"; do
  last="$arg"
done
if [[ "${BCARGO_FAKE_RSYNC_WRITE_ELF:-0}" == "1" && "$last" != *:* ]]; then
  mkdir -p "$(dirname "$last")"
  printf 'fake remote ELF\n' >"$last"
  chmod +x "$last"
fi
exit 0
SH

cat >"$fake_bin/file" <<'SH'
#!/usr/bin/env bash
if [[ -n "${BCARGO_FAKE_FILE_OUTPUT:-}" ]]; then
  printf '%s\n' "$BCARGO_FAKE_FILE_OUTPUT"
  exit 0
fi
exec /usr/bin/file "$@"
SH

cat >"$fake_bin/git" <<'SH'
#!/usr/bin/env bash
if [[ "$1" == "rev-parse" && "$2" == "--show-toplevel" ]]; then
  printf '%s\n' "$BCARGO_FAKE_REPO_ROOT"
  exit 0
fi
echo "unexpected fake git invocation: $*" >&2
exit 1
SH

cat >"$fake_bin/uname" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "${BCARGO_FAKE_UNAME:-$(/usr/bin/uname "$@")}"
SH

chmod +x "$fake_bin/ssh" "$fake_bin/rsync" "$fake_bin/file" "$fake_bin/git" "$fake_bin/uname"

run_fake_bcargo() {
  BCARGO_SSH="$fake_bin/ssh" \
  BCARGO_RSYNC="$fake_bin/rsync" \
  BCARGO_FAKE_SSH_LOG="$ssh_log" \
  BCARGO_FAKE_RSYNC_LOG="$rsync_log" \
  BCARGO_FAKE_REPO_ROOT="$repo_root" \
  BCARGO_PYTHON_ENV=0 \
  PATH="$fake_bin:$PATH" \
    "$repo_root/bin/bcargo" "$@"
}

default_root="/home/tsavo/remote/sugar-bcargo-clean-contract-default"
: >"$ssh_log"
: >"$rsync_log"
BCARGO_REMOTE_ROOT="$default_root" run_fake_bcargo check --manifest-path implementations/rust/Cargo.toml
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
  run_fake_bcargo check --manifest-path implementations/rust/Cargo.toml
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
  run_fake_bcargo check --manifest-path implementations/rust/Cargo.toml 2>"$tmp/unsafe.err"
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
  run_fake_bcargo check --manifest-path implementations/rust/Cargo.toml
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
  run_fake_bcargo check --manifest-path implementations/rust/Cargo.toml
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

elf_root="/home/tsavo/remote/sugar-bcargo-clean-contract-elf"
elf_target="$tmp/local-target"
: >"$ssh_log"
: >"$rsync_log"
if ! BCARGO_REMOTE_ROOT="$elf_root" \
  BCARGO_FAKE_RSYNC_WRITE_ELF=1 \
  BCARGO_FAKE_FILE_OUTPUT="ELF 64-bit LSB executable, x86-64" \
  BCARGO_FAKE_UNAME=Darwin \
  run_fake_bcargo --sync-bin sugar check --manifest-path implementations/rust/Cargo.toml --target-dir "$elf_target" 2>"$tmp/elf.err"
then
  echo "bcargo should skip an incompatible synced binary without failing the remote cargo command" >&2
  cat "$tmp/elf.err" >&2
  exit 1
fi
if [[ -e "$elf_target/debug/sugar" ]]; then
  echo "bcargo deposited a foreign-platform ELF into a local target dir" >&2
  exit 1
fi
if ! grep -Fq "crime=foreign-platform-binary" "$tmp/elf.err"; then
  echo "bcargo skipped/deposited an ELF without the expected cold-agent executable diagnostic" >&2
  cat "$tmp/elf.err" >&2
  exit 1
fi
