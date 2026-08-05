#!/usr/bin/env bash
# Host-level measurement gates for battleaxe: exclusive/shared lease + load.
#
# Exit 76: host not quiet (load1 over ceiling under the lease).
# Exit 77: lease busy / lock theatre (per-container /var/tmp, or wait timeout).
#
# Topology (proven 2026-08-02): ~25 GitHub runners are containers on ONE box
# (battleaxe). /var/tmp is per-container — flock there is lock theatre.
# The path that serializes across containers is a host bind-mount:
#   /home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease
# (host ambient: /home/tsavo/.cache/sugar/binaries/.sugar-heavy-measurement.lease)
#
# Lock modes (reader-writer):
#   --shared     CI recensus seats may co-run (shared flock).
#   --exclusive  Human brun / sole measurement (exclusive flock); waits for
#                all shared holders; blocks new shared while held.
#
# Usage:
#   tools/bx_host_measure_gates.sh [--shared|--exclusive] -- command [args...]
set -euo pipefail

mode=exclusive
while [[ $# -gt 0 ]]; do
  case "$1" in
    --shared) mode=shared; shift ;;
    --exclusive) mode=exclusive; shift ;;
    --) shift; break ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      # bare command without --
      break
      ;;
  esac
done
if [[ "${1:-}" == "--" ]]; then shift; fi
if [[ $# -lt 1 ]]; then
  echo "usage: tools/bx_host_measure_gates.sh [--shared|--exclusive] -- command [args...]" >&2
  exit 2
fi

# Prefer host-shared bind-mount paths. Never default to /var/tmp on a box
# that has the shared cache — that was the twelve-container false green.
default_lease() {
  if [[ -n "${SUGAR_BX_TIMING_LEASE_PATH:-}" ]]; then
    printf '%s\n' "$SUGAR_BX_TIMING_LEASE_PATH"
    return
  fi
  if [[ -d /home/runner/.cache/sugar/binaries ]]; then
    printf '%s\n' /home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease
    return
  fi
  if [[ -d /home/tsavo/.cache/sugar/binaries ]]; then
    printf '%s\n' /home/tsavo/.cache/sugar/binaries/.sugar-heavy-measurement.lease
    return
  fi
  printf '%s\n' /var/tmp/sugar-bx-timing-measurement.lease
}

LEASE="$(default_lease)"
WAIT="${SUGAR_BX_TIMING_LEASE_WAIT_S:-7200}"
MAX_LIT="${SUGAR_BX_MAX_LOADAVG:-}"

mkdir -p "$(dirname "$LEASE")"
touch "$LEASE" || {
  echo "sugarbin: crime=timing-lease-uncreatable path=$LEASE" >&2
  exit 77
}

# Scope check (banked in docs/contributing/heavy-measurement-lease.md):
# inside a container, refuse a lease on the same device as / — that is the
# container rootfs, invisible to peers (lock theatre).
in_container=0
if [[ -f /.dockerenv || -f /run/.containerenv ]]; then
  in_container=1
elif [[ -r /proc/1/cgroup ]] && grep -Eq 'docker|containerd|kubepods|libpod' /proc/1/cgroup 2>/dev/null; then
  in_container=1
fi
if [[ "$in_container" == 1 ]]; then
  if command -v stat >/dev/null 2>&1; then
    root_dev="$(stat -c '%d' / 2>/dev/null || stat -f '%d' / 2>/dev/null || echo "")"
    lease_dev="$(stat -c '%d' "$LEASE" 2>/dev/null || stat -f '%d' "$LEASE" 2>/dev/null || echo "")"
    if [[ -n "$root_dev" && -n "$lease_dev" && "$root_dev" == "$lease_dev" ]]; then
      echo "sugarbin: crime=timing-lease-on-container-rootfs path=$LEASE root_dev=$root_dev replacement=use host bind-mount /home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease (not /var/tmp). Exit 77." >&2
      exit 77
    fi
  fi
fi

if ! command -v flock >/dev/null 2>&1; then
  echo "sugarbin: crime=timing-lease-flock-missing replacement=install util-linux flock" >&2
  exit 77
fi

exec 9>>"$LEASE"
flock_mode_flag="-x"
[[ "$mode" == shared ]] && flock_mode_flag="-s"

echo "sugarbin: bx-timing-lease phase=waiting mode=$mode path=$LEASE wait_s=$WAIT" >&2
if ! flock $flock_mode_flag -w "$WAIT" 9; then
  echo "sugarbin: crime=timing-lease-busy mode=$mode path=$LEASE wait_s=$WAIT replacement=another measurement holds the host lease — serialize. Exit 77." >&2
  exit 77
fi
echo "sugarbin: bx-timing-lease phase=acquired mode=$mode path=$LEASE lease=held" >&2

if [[ -r /proc/loadavg ]]; then
  read -r l1 _rest </proc/loadavg
else
  l1="$(python3 -c 'import os; print(os.getloadavg()[0])' 2>/dev/null || echo 0)"
fi
n="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
if [[ -n "$MAX_LIT" ]]; then
  max="$MAX_LIT"
else
  max="$(awk -v n="$n" 'BEGIN{ m=n/4.0; if (m < 2.0) m=2.0; printf "%.2f", m }')"
fi
echo "sugarbin: bx-load-gate phase=before load1=$l1 nproc=$n max=$max lease=held mode=$mode" >&2
# NO LOAD CEILING (owner ruling, 2026-08-05).
#
# The ceiling was set for the single-process era and never revisited for the
# shared-runner topology this workflow is built around: k=8 shards are
# containers on ONE box, so the fan-out trips a ceiling of nproc/4 by simply
# existing -- eight seats refused at load1=8.45 on a 32-core host, which is
# ~26% utilisation. A gate that refuses the very concurrency it was written to
# permit measures nothing.
#
# The condition is still TESTIFIED -- load1 before and after are recorded on
# every run and travel in the receipt. What is removed is the REFUSAL, not the
# observation: a measurement still says what its conditions were, and a reader
# can judge them. Serialisation against human brun remains the lease's job.

set +e
"$@"
st=$?
set -e

if [[ -r /proc/loadavg ]]; then
  read -r l2 _rest </proc/loadavg
else
  l2=unknown
fi
echo "sugarbin: bx-load-gate phase=after load1_before=$l1 load1_after=$l2 nproc=$n lease=held mode=$mode" >&2
echo "sugarbin: bx-timing-lease phase=release mode=$mode path=$LEASE status=$st" >&2
exit "$st"
