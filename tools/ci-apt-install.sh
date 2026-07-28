#!/usr/bin/env bash
set -euo pipefail

[[ $# -gt 0 ]] || { echo "usage: tools/ci-apt-install.sh PACKAGE..." >&2; exit 2; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

missing_packages() {
  local package
  for package in "$@"; do
    dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -Fqx installed \
      || printf '%s\n' "$package"
  done
}

# dpkg-query answers "did apt install this", which is not the question the
# build asks. The question is "is the tool usable". A b3sum acquired through
# cargo lives in ~/.cargo/bin and is invisible to dpkg, so the apt path was
# being entered for a dependency that was already satisfied. Packages whose
# provided command is known get asked the real question.
provided_command() {
  case "$1" in
    b3sum) printf 'b3sum\n' ;;
    z3) printf 'z3\n' ;;
    cvc5) printf 'cvc5\n' ;;
    maven) printf 'mvn\n' ;;
    unzip) printf 'unzip\n' ;;
    time) printf '/usr/bin/time\n' ;;
    *) return 1 ;;
  esac
}

command_satisfied() {
  local cmd
  cmd="$(provided_command "$1")" || return 1
  if [[ "$cmd" == /* ]]; then
    [[ -x "$cmd" ]]
    return
  fi
  command -v "$cmd" >/dev/null 2>&1
}

unsatisfied_packages() {
  local package
  for package in "$@"; do
    command_satisfied "$package" || printf '%s\n' "$package"
  done
}

# b3sum participates in content addressing (bin/sugarbin stamps, source
# stamps, consensus digests). It is pinned in sugar-build.toml and acquired
# from crates.io, whose index carries a sha256 for every .crate archive that
# cargo verifies before building. That is a checksum-verified acquisition, and
# it never touches apt, so it cannot inherit apt's lock contention.
b3sum_pin() {
  sed -n 's/^b3sum[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$root/sugar-build.toml" | head -1
}

install_b3sum_from_crates_io() {
  local pin
  pin="$(b3sum_pin)"
  if [[ -z "$pin" ]]; then
    echo "::error::sugar-build.toml carries no b3sum pin; refusing to acquire an unpinned hashing tool" >&2
    return 1
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    echo "::error::cargo unavailable; cannot acquire pinned b3sum $pin without apt" >&2
    return 1
  fi
  echo "ci-apt: acquiring b3sum $pin from crates.io (checksum-verified, no apt)"
  cargo install b3sum --locked --version "$pin"
}

# These are self-hosted runners, so the normal path is that provisioning has
# already installed every dependency. Check that before touching any lock or
# sudo boundary. In particular, never make a cache-hit job wait behind apt.
mapfile -t missing < <(missing_packages "$@")
if ((${#missing[@]} == 0)); then
  echo "ci-apt: already installed: $*"
  exit 0
fi

mapfile -t missing < <(unsatisfied_packages "${missing[@]}")
if ((${#missing[@]} == 0)); then
  echo "ci-apt: already on PATH: $*"
  exit 0
fi

# Anything acquirable without apt is acquired without apt. An eliminated apt
# dependency cannot flake on a lock held by a stale process.
remaining=()
for package in "${missing[@]}"; do
  if [[ "$package" == "b3sum" ]]; then
    install_b3sum_from_crates_io
    continue
  fi
  remaining+=("$package")
done
if ((${#remaining[@]} == 0)); then
  exit 0
fi
wanted=("${remaining[@]}")
missing=("${remaining[@]}")

# Retry budget is a seam so the fail-loud path is testable in seconds. It is
# not a knob for making a real failure quieter: exhausting it is still red.
attempts="${SUGAR_CI_APT_ATTEMPTS:-60}"
for attempt in $(seq 1 "$attempts"); do
  # A racing lane may have installed the package while this lane was waiting.
  mapfile -t missing < <(missing_packages "${wanted[@]}")
  if ((${#missing[@]} > 0)); then
    mapfile -t missing < <(unsatisfied_packages "${missing[@]}")
  fi
  if ((${#missing[@]} == 0)); then
    echo "ci-apt: installed by another lane: ${wanted[*]}"
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
  echo "ci-apt: native package database busy (attempt $attempt/$attempts); retrying" >&2
  ps -eo pid,ppid,etimes,cmd 2>/dev/null \
    | grep -E '[a]pt-get|[d]pkg|[u]nattended-upgrade' >&2 \
    || true
  sleep 2
done

# Name the holder. The observed failure was an orphaned `apt-get update`
# (parent sudo reparented to init) holding /var/lib/apt/lists/lock for hours;
# no retry window reaches that, so the report must point at the process rather
# than at the clock.
echo "::error::apt unavailable for ${missing[*]} after $attempts attempts; long-lived lock holders below (etimes = seconds alive)" >&2
ps -eo pid,ppid,etimes,cmd 2>/dev/null \
  | grep -E '[a]pt-get|[d]pkg|[u]nattended-upgrade' >&2 \
  || echo "::error::no apt/dpkg process visible; the lock owner is outside this namespace or already dead" >&2
exit 1
