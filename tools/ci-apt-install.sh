#!/usr/bin/env bash
set -euo pipefail

[[ $# -gt 0 ]] || { echo "usage: tools/ci-apt-install.sh PACKAGE..." >&2; exit 2; }
command -v flock >/dev/null 2>&1 || { echo "::error::flock is required to coordinate apt"; exit 2; }

# Self-hosted jobs share the host package database. Test execution is parallel;
# mutation of that one database is not. The repository lock coordinates our
# lanes, while the retry handles cloud-init/unattended-upgrades outside it.
exec 9>/tmp/sugar-ci-apt.lock
flock -w 600 9 || { echo "::error::timed out waiting for Sugar's apt owner"; exit 1; }

missing=()
for package in "$@"; do
  dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -Fqx installed \
    || missing+=("$package")
done
if ((${#missing[@]} == 0)); then
  echo "ci-apt: already installed: $*"
  exit 0
fi

for attempt in $(seq 1 60); do
  if sudo apt-get update -y \
      && sudo apt-get install -y --no-install-recommends "${missing[@]}"; then
    echo "ci-apt: installed: ${missing[*]}"
    exit 0
  fi
  echo "ci-apt: package database busy (attempt $attempt/60); retrying" >&2
  sleep 2
done

echo "::error::apt remained unavailable after 120 seconds" >&2
exit 1
