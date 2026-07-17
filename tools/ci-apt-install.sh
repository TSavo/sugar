#!/usr/bin/env bash
set -euo pipefail

[[ $# -gt 0 ]] || { echo "usage: tools/ci-apt-install.sh PACKAGE..." >&2; exit 2; }

missing_packages() {
  local package
  for package in "$@"; do
    dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -Fqx installed \
      || printf '%s\n' "$package"
  done
}

# These are self-hosted runners, so the normal path is that provisioning has
# already installed every dependency. Check that before touching any lock or
# sudo boundary. In particular, never make a cache-hit job wait behind apt.
mapfile -t missing < <(missing_packages "$@")
if ((${#missing[@]} == 0)); then
  echo "ci-apt: already installed: $*"
  exit 0
fi

for attempt in $(seq 1 60); do
  # A racing lane may have installed the package while this lane was waiting.
  mapfile -t missing < <(missing_packages "$@")
  if ((${#missing[@]} == 0)); then
    echo "ci-apt: installed by another lane: $*"
    exit 0
  fi

  # apt/dpkg already own authoritative process-scoped locks. A repository
  # flock is weaker: cancelled jobs can leave an apt descendant holding its
  # inherited descriptor after the runner shell exits. Use the native lock and
  # bounded retry instead, so ownership cannot outlive the package process.
  if sudo apt-get -o DPkg::Lock::Timeout=10 update -y \
      && sudo apt-get -o DPkg::Lock::Timeout=10 install -y --no-install-recommends "${missing[@]}"; then
    echo "ci-apt: installed: ${missing[*]}"
    exit 0
  fi
  echo "ci-apt: native package database busy (attempt $attempt/60); retrying" >&2
  ps -eo pid,ppid,etimes,cmd 2>/dev/null \
    | grep -E '[a]pt-get|[d]pkg|[u]nattended-upgrade' >&2 \
    || true
  sleep 2
done

echo "::error::apt remained unavailable after 120 seconds" >&2
exit 1
