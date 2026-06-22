#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
log="$tmp/rsync.log"

cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
exit 0
SH

cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BCARGO_FAKE_RSYNC_LOG"
exit 0
SH

chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

BCARGO_SSH="$fake_bin/ssh" \
BCARGO_RSYNC="$fake_bin/rsync" \
BCARGO_FAKE_RSYNC_LOG="$log" \
BCARGO_PYTHON_ENV=0 \
BCARGO_REMOTE_ROOT=/tmp/bcargo-sync-self-attest-test \
  "$repo_root/bin/bcargo" check --manifest-path implementations/rust/Cargo.toml

if ! grep -Fq "sugar-release.toml" "$log"; then
  echo "bcargo did not sync sugar-release.toml; remote make self-attest cannot read its manifest" >&2
  exit 1
fi
