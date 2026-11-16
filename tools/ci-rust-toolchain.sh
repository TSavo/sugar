#!/usr/bin/env bash
# The pinned Rust toolchain for CI, from the runner's own rustup (#8416).
#
# WHY THIS EXISTS
#
# .github/actions/setup-rust-cache used dtolnay/rust-toolchain. On the
# self-hosted runners it went to the network on every job even though the
# pinned toolchain was installed:
#   * ~/.cargo/bin is not on the runner's PATH when the step starts, so its
#     "Install rustup if needed" re-ran the installer from sh.rustup.rs;
#   * `rustup toolchain install <pin>` fetches the channel manifest's
#     checksum from static.rust-lang.org even when the toolchain is present,
#     and dtolnay retries only a release-server checksum race.
# One TLS reset on that fetch (channel-rust-1.96.0.toml.sha256) failed suite
# shard 2 of main-scorecard run 43832361876 before any test ran.
#
# Now the installed toolchain is used as it is, with no network at all:
# rustup is looked for in $CARGO_HOME/bin before PATH; `rustup toolchain
# list`, `rustup component list --installed` and `rustup default` (all local)
# decide whether anything is missing; implicit installs are off while this
# script runs (RUSTUP_AUTO_INSTALL=0); `rustup show` and `rustup update` are
# never run; self-update is disabled once. Only a missing rustup, toolchain or
# component goes to the network, each under a bounded retry.
#
# The pin is the build contract's: `rust = "..."` in sugar-build.toml.
#
# Input (env): SUGAR_RUST_COMPONENTS, comma- or space-separated (default
# rustfmt). Exports (GITHUB_ENV / GITHUB_PATH), as dtolnay/rust-toolchain did:
# CARGO_HOME, $CARGO_HOME/bin on PATH, CARGO_INCREMENTAL=0 and
# CARGO_TERM_COLOR=always unless already set; the pin is the runner's rustup
# default (set only when it is not already), so a rust-toolchain.toml in a
# project directory still applies there.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
toolchain="$(awk -F'"' '/^rust = "/ { print $2; exit }' "$repo/sugar-build.toml")"
if [ -z "$toolchain" ]; then
  echo "::error::no 'rust = \"...\"' pin in sugar-build.toml"
  exit 1
fi
components="${SUGAR_RUST_COMPONENTS-rustfmt}"
cargo_home="${CARGO_HOME:-$HOME/.cargo}"
export CARGO_HOME="$cargo_home"
export PATH="$cargo_home/bin:$PATH"
export RUSTUP_AUTO_INSTALL=0
export RUSTUP_MAX_RETRIES="${RUSTUP_MAX_RETRIES:-5}"
export RUSTUP_PERMIT_COPY_RENAME=1
t0=$(date +%s)
fetched=none

# retry <what> <command...>: four attempts, 15, 30 and 45 seconds apart.
retry() {
  local what="$1" attempt
  shift
  for attempt in 1 2 3 4; do
    if "$@"; then return 0; fi
    if [ "$attempt" -lt 4 ]; then
      echo "::warning::$what failed (attempt $attempt of 4); retrying in $((attempt * 15))s"
      sleep $((attempt * 15))
    fi
  done
  echo "::error::$what failed after 4 attempts"
  return 1
}

install_rustup() {
  local tmp rc=0
  tmp="$(mktemp -d)"
  curl --proto '=https' --tlsv1.2 --retry 5 --retry-connrefused --location \
    --silent --show-error --fail -o "$tmp/rustup-init.sh" https://sh.rustup.rs || rc=$?
  if [ "$rc" -eq 0 ]; then
    sh "$tmp/rustup-init.sh" -y --default-toolchain none --no-modify-path --profile minimal || rc=$?
  fi
  rm -rf "$tmp"
  return "$rc"
}

if ! command -v rustup >/dev/null 2>&1; then
  echo "rust toolchain: no rustup on this runner; installing it"
  retry "rustup install" install_rustup
  fetched="rustup"
fi

# Whole output first, then grep: `rustup ... | grep -q` under pipefail can
# fail on SIGPIPE and read as "not installed".
installed="$(rustup toolchain list 2>/dev/null || true)"
if grep -Eq "^${toolchain//./\\.}-" <<< "$installed"; then
  echo "rust toolchain: $toolchain installed; nothing downloaded"
else
  retry "rustup toolchain install $toolchain" \
    rustup toolchain install "$toolchain" --profile minimal --no-self-update
  fetched="$fetched toolchain"
fi

have="$(rustup component list --installed --toolchain "$toolchain" 2>/dev/null || true)"
for component in ${components//,/ }; do
  if grep -Eq "^${component}(-|$)" <<< "$have"; then continue; fi
  retry "rustup component add $component" rustup component add "$component" --toolchain "$toolchain"
  fetched="$fetched $component"
done

default="$(rustup default 2>/dev/null || true)"
if ! grep -Eq "^${toolchain//./\\.}-" <<< "$default"; then
  rustup default "$toolchain"
fi
settings="${RUSTUP_HOME:-$HOME/.rustup}/settings.toml"
if ! grep -qs 'auto_self_update = "disable"' "$settings"; then
  rustup set auto-self-update disable || echo "::warning::could not disable rustup self-update"
fi

rustc +"$toolchain" --version --verbose
cargo +"$toolchain" --version

if [ -n "${GITHUB_ENV:-}" ]; then
  echo "CARGO_HOME=$cargo_home" >> "$GITHUB_ENV"
  [ -n "${CARGO_INCREMENTAL+set}" ] || echo "CARGO_INCREMENTAL=0" >> "$GITHUB_ENV"
  [ -n "${CARGO_TERM_COLOR+set}" ] || echo "CARGO_TERM_COLOR=always" >> "$GITHUB_ENV"
fi
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$cargo_home/bin" >> "$GITHUB_PATH"
fi
echo "rust toolchain: $toolchain ready in $(( $(date +%s) - t0 ))s (fetched: ${fetched# })"
