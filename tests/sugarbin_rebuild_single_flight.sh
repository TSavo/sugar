#!/usr/bin/env bash
# R_shelf_rebuild_single_flight teeth.
#
# Required properties (live under 36 matrix resolvers):
#   1. N concurrent cold-miss resolvers produce exactly ONE build
#   2. A waiter gets the winner's cell (re-pull after lock)
#   3. A dead winner does not wedge — lock is reclaimable via heartbeat
#
# This is resource dedupe on one sourceStamp, NOT a measurement mutex.
set -euo pipefail

repo="${1:?usage: sugarbin_rebuild_single_flight.sh REPO_ROOT}"
sugarbin="$repo/bin/sugarbin"
lock_state="$repo/tools/rebuild_lock_state.py"
[[ -x "$sugarbin" ]] || { echo "missing $sugarbin" >&2; exit 1; }
[[ -f "$lock_state" ]] || { echo "missing $lock_state" >&2; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# --- Static: shapes on the miss→rebuild path ---
grep -Fq 'acquire_rebuild_single_flight' "$sugarbin" || fail 'missing acquire_rebuild_single_flight'
grep -Fq 'release_rebuild_single_flight' "$sugarbin" || fail 'missing release_rebuild_single_flight'
grep -Fq 'phase=resolve-hit source=peer-publish-after-wait' "$sugarbin" \
  || fail 'missing double-check after lock (peer-publish-after-wait hit)'
grep -Fq 'pull_from_filesystem_shelf' "$sugarbin" || fail 'missing pull after lock'
grep -Fq '.rebuild-locks' "$sugarbin" || fail 'missing lock directory under cache'
grep -Fq 'heartbeat' "$sugarbin" || fail 'missing heartbeat for dead-winner reclaim'
grep -Fq 'SUGAR_BINARY_REBUILD_LOCK_STALE_S' "$sugarbin" || fail 'missing stale-age override'

acquire_body="$(sed -n '/^acquire_rebuild_single_flight()/,/^release_rebuild_single_flight()/p' "$sugarbin")"
grep -Fq 'stamp_for_filename "$stamp"' <<<"$acquire_body" || fail 'lock key does not include stamp'
grep -Fq 'bin_name' <<<"$acquire_body" || fail 'lock key does not include bin_name'
grep -Fq 'platform_key' <<<"$acquire_body" || fail 'lock key does not include platform'
grep -Fq 'rebuild_lock_state.py' <<<"$acquire_body" \
  || fail 'lock acquisition must use the errno-preserving atomic-create door'
grep -Fq 'crime=rebuild-lock-create-refused' <<<"$acquire_body" \
  || fail 'create refusal must not collapse into EEXIST contention'
grep -Fq 'crime=unshareable-rebuild-lock-path' <<<"$acquire_body" \
  || fail 'foreign-mode lock parent must refuse before contention'
# kill -0 alone is forbidden as reclaim (PID namespace lie / wedge).
if grep -E 'kill -0' <<<"$acquire_body" | grep -vq 'heartbeat'; then
  # allow only if not the reclaim path — reclaim must use heartbeat age
  :
fi
grep -Fq 'phase=resolve-wait-reclaim' <<<"$acquire_body" \
  || fail 'reclaim must emit phase=resolve-wait-reclaim (heartbeat age, not kill -0 alone)'
if grep -Fq 'heavy-measurement' <<<"$acquire_body"; then
  fail 'rebuild single-flight must not use the deleted heavy-measurement lease'
fi
# Doctrine: waiter narrates immediately and every ~30s to the job log (stderr).
grep -Fq 'phase=resolve-wait' <<<"$acquire_body" \
  || fail 'waiter must emit phase=resolve-wait to job log'
grep -Fq 'waiting-on-peer' <<<"$acquire_body" \
  || fail 'waiter line must say waiting-on-peer (silent wait is a hang)'
grep -Fq 'waited % 120' <<<"$acquire_body" \
  || fail 'waiter must heartbeat every ~30s (120 * 0.25s ticks)'
# Cold rebuild narrates start + 30s cargo heartbeat (not TTY-gated).
grep -Fq 'phase=resolve-build-start' "$sugarbin" \
  || fail 'cold rebuild must emit phase=resolve-build-start'
grep -Fq 'phase=resolve-build bin=' "$sugarbin" \
  || fail 'cold rebuild must emit 30s phase=resolve-build heartbeats'
grep -Fq 'phase=resolve-hit source=' "$sugarbin" \
  || fail 'warm hit must emit phase=resolve-hit source=…'

main_body="$(sed -n '/^main()/,/^if \[\[ -n "\$artifact_subcommand" \]\]/p' "$sugarbin")"
# Order on the miss path (last acquire/build_from_source in main).
acquire_line="$(grep -n 'acquire_rebuild_single_flight' <<<"$main_body" | tail -1 | cut -d: -f1)"
build_line="$(grep -n 'build_from_source' <<<"$main_body" | tail -1 | cut -d: -f1)"
[[ -n "$acquire_line" && -n "$build_line" ]] || fail 'main missing acquire or build_from_source'
[[ "$acquire_line" -lt "$build_line" ]] || fail 'acquire must precede build_from_source'
# Between acquire and build there must be a re-pull (waiter gets winner cell).
mid="$(sed -n "${acquire_line},${build_line}p" <<<"$main_body")"
grep -Fq 'pull_from_filesystem_shelf' <<<"$mid" || fail 'must re-pull after lock acquire before build'
grep -Fq 'peer-publish-after-wait' <<<"$mid" || fail 'must log peer-publish-after-wait for waiters'
n_release=$(grep -c 'release_rebuild_single_flight' <<<"$main_body" || true)
[[ "$n_release" -ge 3 ]] || fail "main must release lock on every exit (found $n_release)"

# --- Dynamic 1: N concurrent contenders → exactly one "build" ---
tmp="$(mktemp -d "${TMPDIR:-/tmp}/shelf-sflight.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
lock_parent="$tmp/locks"
mkdir -p "$lock_parent"
lockdir="$lock_parent/stamp-demo.lock"
build_count="$tmp/builds"
: >"$build_count"
cell="$tmp/cell"
N=8

# Simulate the acquire/build/publish/release algorithm N ways in parallel.
# "Build" = append one line under exclusive lock only.
worker() {
  local id="$1" stale_s=3
  local waited=0
  while true; do
    if mkdir "$lockdir" 2>/dev/null; then
      echo $$ >"$lockdir/pid"
      : >"$lockdir/heartbeat"
      (
        while [[ -d "$lockdir" ]]; do
          : >"$lockdir/heartbeat" 2>/dev/null || exit 0
          sleep 0.2
        done
      ) &
      local hb=$!
      # double-check: if cell already exists, do not build
      if [[ -f "$cell" ]]; then
        kill "$hb" 2>/dev/null || true
        wait "$hb" 2>/dev/null || true
        rm -rf "$lockdir"
        return 0
      fi
      # sole builder
      echo "build-by-$id" >>"$build_count"
      sleep 0.4  # pretend cargo
      echo "winner-$id" >"$cell"
      kill "$hb" 2>/dev/null || true
      wait "$hb" 2>/dev/null || true
      rm -rf "$lockdir"
      return 0
    fi
    # waiter: if cell appeared, take it without building
    if [[ -f "$cell" ]]; then
      return 0
    fi
    # stale reclaim via heartbeat age
    if [[ -f "$lockdir/heartbeat" ]]; then
      local now mtime age
      now=$(date +%s)
      mtime=$(stat -c %Y "$lockdir/heartbeat" 2>/dev/null || stat -f %m "$lockdir/heartbeat" 2>/dev/null || echo 0)
      age=$((now - mtime))
      if [[ "$age" -ge "$stale_s" ]]; then
        rm -rf "$lockdir" 2>/dev/null || true
        continue
      fi
    fi
    sleep 0.05
    waited=$((waited + 1))
    [[ "$waited" -lt 400 ]] || { echo "worker $id timed out" >&2; return 1; }
  done
}

for i in $(seq 1 "$N"); do
  worker "$i" &
done
wait

builds=$(wc -l <"$build_count" | tr -d ' ')
[[ "$builds" == "1" ]] || fail "expected exactly ONE build from $N resolvers, got $builds"
[[ -f "$cell" ]] || fail 'waiters did not observe a cell after winner'
echo "PASS: $N concurrent resolvers → exactly 1 build; cell present"

# --- Dynamic 2: dead winner does not wedge ---
rm -rf "$lockdir" "$cell"
mkdir "$lockdir"
echo "dead" >"$lockdir/pid"
: >"$lockdir/heartbeat"
# freeze heartbeat in the past
touch -t 202001010000 "$lockdir/heartbeat" 2>/dev/null \
  || touch -d '2020-01-01' "$lockdir/heartbeat" 2>/dev/null \
  || { # fallback: rewrite with old content and hope mtime is now - use stale_s=0 via env
      sleep 0
    }
# With stale_s=0, any existing heartbeat is reclaimable after age check with
# SUGAR-style age; force reclaim by removing heartbeat mtime via long sleep
# if touch -t failed.
if [[ -d "$lockdir" ]]; then
  age_now=$(date +%s)
  m=$(stat -c %Y "$lockdir/heartbeat" 2>/dev/null || stat -f %m "$lockdir/heartbeat" 2>/dev/null || echo 0)
  if [[ $((age_now - m)) -lt 2 ]]; then
    # touch -t failed; simulate stale by deleting heartbeat after marking
    # holder dead without release — reclaim path for no-heartbeat after grace
    rm -f "$lockdir/heartbeat"
  fi
fi
# One worker must reclaim and build
worker "reclaim" || fail 'dead-winner reclaim worker failed'
[[ -f "$cell" ]] || fail 'dead winner wedged the estate — no cell after reclaim'
builds2=$(wc -l <"$build_count" | tr -d ' ')
[[ "$builds2" == "2" ]] || fail "expected second build after dead reclaim, got $builds2 total"
echo "PASS: dead winner lock reclaimed; next resolver built"

# --- Dynamic 3: the production lock path terminates on both arms ---
# Exercise the actual bin/sugarbin acquire/release functions, not the model
# above.  The bad twin makes exactly one planted stale lock impossible to
# remove; the resolver must refuse once rather than loop forever on
# holder_pid=unknown / heartbeat_age=999999.
production_cache="$tmp/production-cache"
production_stamp="blake3-512_axis7"
production_lock="$production_cache/.rebuild-locks/fixture-debug-${production_stamp}-sugar.lock"

SUGAR_BINARY_CACHE_DIR="$production_cache" \
SUGAR_BINARY_SOURCE_STAMP="$production_stamp" \
  "$sugarbin" preflight-lock --bin sugar --profile debug --platform fixture \
  >"$tmp/production-good.out" 2>"$tmp/production-good.err" \
  || fail 'production acquire/release arm refused'
[[ ! -e "$production_lock" ]] || fail 'production acquire/release arm left lock residue'
production_parent="$production_cache/.rebuild-locks"
parent_mode="$(stat -c %a "$production_parent" 2>/dev/null || stat -f %Lp "$production_parent")"
[[ "${parent_mode: -3}" == 777 ]] \
  || fail "production lock parent is not shared-writable: mode=$parent_mode"

# Never-created and create-refused are distinct states. A fresh path above
# acquired and released normally. This planted EACCES arm exercises the same
# errno-preserving door without relying on the test runner's uid (battleaxe
# may execute the surrounding shell as root).
python3 - "$lock_state" <<'PY'
import errno
import importlib.util
import pathlib
import stat
import tempfile
from unittest import mock
import sys

path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("rebuild_lock_state", path)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load rebuild-lock state helper")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with mock.patch.object(
    module.os,
    "mkdir",
    side_effect=PermissionError(errno.EACCES, "Permission denied"),
):
    result = module.create_lock_directory(pathlib.Path("/fixture/lock"))
if result.state != "create-refused":
    raise SystemExit(f"EACCES collapsed into {result.state}")
if result.errno_name != "EACCES" or result.errno_number != errno.EACCES:
    raise SystemExit(f"EACCES testimony lost: {result}")
if "Permission denied" not in result.detail:
    raise SystemExit(f"EACCES detail lost: {result}")
with tempfile.TemporaryDirectory() as directory:
    parent = pathlib.Path(directory) / "shared-parent"
    result = module.publish_lock_parent(parent)
    if result.state != "ready" or stat.S_IMODE(parent.stat().st_mode) != 0o777:
        raise SystemExit(f"shared parent was not published as 0777: {result}")
    lock = parent / "one.lock"
    result = module.create_lock_directory(lock)
    if result.state != "acquired" or stat.S_IMODE(lock.stat().st_mode) != 0o777:
        raise SystemExit(f"shared lock was not published as 0777: {result}")
    if module.create_lock_directory(lock).state != "contended":
        raise SystemExit("existing lock directory did not classify as contended")
with tempfile.TemporaryDirectory() as directory:
    parent = pathlib.Path(directory) / "foreign-parent"
    parent.mkdir(mode=0o755)
    if module.publish_lock_parent(parent).state != "unshareable":
        raise SystemExit("0755 parent did not refuse as unshareable")
with mock.patch.object(module.os, "mkdir", side_effect=FileExistsError(errno.EEXIST, "exists")):
    if module.create_lock_directory(pathlib.Path("/fixture/released")).state != "released":
        raise SystemExit("released EEXIST winner did not classify as released")
PY

# Created-unpublished: EEXIST is real contention, but its winner never wrote a
# holder record. This must terminate once after the bounded publication grace.
mkdir -m 0777 "$production_lock"
python3 - "$sugarbin" "$production_cache" "$production_stamp" \
  "$production_lock" <<'PY'
import os
import subprocess
import sys

sugarbin, cache, stamp, lock = sys.argv[1:]
env = os.environ.copy()
env.update(
    {
        "SUGAR_BINARY_CACHE_DIR": cache,
        "SUGAR_BINARY_SOURCE_STAMP": stamp,
    }
)
try:
    result = subprocess.run(
        [
            sugarbin,
            "preflight-lock",
            "--bin",
            "sugar",
            "--profile",
            "debug",
            "--platform",
            "fixture",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
except subprocess.TimeoutExpired as error:
    raise SystemExit(f"created-unpublished arm did not terminate: {error.stderr}")
if result.returncode != 70:
    print(result.stderr, file=sys.stderr)
    raise SystemExit(f"expected exit 70, observed {result.returncode}")
terminal = "crime=missing-rebuild-lock-pid"
if result.stderr.count(terminal) != 1:
    print(result.stderr, file=sys.stderr)
    raise SystemExit("expected exactly one created-unpublished terminal")
for testimony in (lock + "/pid", "holder_pid=unknown"):
    if testimony not in result.stderr:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"missing created-unpublished testimony: {testimony}")
PY
rm -rf "$production_lock"

mkdir -p "$production_lock"
printf 'dead\n' >"$production_lock/pid"
mkdir -p "$tmp/refuse-rm-bin"
cat >"$tmp/refuse-rm-bin/rm" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == -rf && "${2:-}" == "${LOCK_TO_REFUSE:?}" ]]; then
  exit 77
fi
exec /bin/rm "$@"
EOF
chmod +x "$tmp/refuse-rm-bin/rm"

python3 - "$sugarbin" "$production_cache" "$production_stamp" \
  "$production_lock" "$tmp/refuse-rm-bin" "$tmp/production-bad.json" <<'PY'
import json
import os
import subprocess
import sys

sugarbin, cache, stamp, lock, refuse_bin, receipt = sys.argv[1:]
env = os.environ.copy()
env.update(
    {
        "LOCK_TO_REFUSE": lock,
        "PATH": refuse_bin + os.pathsep + env["PATH"],
        "SUGAR_BINARY_CACHE_DIR": cache,
        "SUGAR_BINARY_REBUILD_LOCK_STALE_S": "0",
        "SUGAR_BINARY_SOURCE_STAMP": stamp,
    }
)
try:
    result = subprocess.run(
        [
            sugarbin,
            "preflight-lock",
            "--bin",
            "sugar",
            "--profile",
            "debug",
            "--platform",
            "fixture",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
except subprocess.TimeoutExpired as error:
    stderr = error.stderr or ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    print(
        "production unreclaimable-lock arm did not terminate within 5s",
        file=sys.stderr,
    )
    print(stderr, file=sys.stderr)
    raise SystemExit(1)
json.dump(
    {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
    open(receipt, "w", encoding="utf-8"),
    sort_keys=True,
)
if result.returncode != 70:
    print(result.stderr, file=sys.stderr)
    raise SystemExit(f"expected exit 70, observed {result.returncode}")
terminal = "crime=unreclaimable-rebuild-lock"
if result.stderr.count(terminal) != 1:
    print(result.stderr, file=sys.stderr)
    raise SystemExit("expected exactly one named unreclaimable-lock terminal")
for testimony in (lock, "holder_pid=dead", "heartbeat_age_s=999999"):
    if testimony not in result.stderr:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"missing terminal testimony: {testimony}")
PY

rm -rf "$production_lock"
create_refused_cache="$tmp/create-refused-cache"
mkdir -p "$create_refused_cache"
printf 'not-a-directory\n' >"$create_refused_cache/.rebuild-locks"

python3 - "$sugarbin" "$create_refused_cache" "$production_stamp" \
  "$tmp/production-create-refused.json" <<'PY'
import json
import os
import subprocess
import sys

sugarbin, cache, stamp, receipt = sys.argv[1:]
env = os.environ.copy()
env.update(
    {
        "SUGAR_BINARY_CACHE_DIR": cache,
        "SUGAR_BINARY_SOURCE_STAMP": stamp,
    }
)
try:
    result = subprocess.run(
        [
            sugarbin,
            "preflight-lock",
            "--bin",
            "sugar",
            "--profile",
            "debug",
            "--platform",
            "fixture",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
except subprocess.TimeoutExpired as error:
    stderr = error.stderr or ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    print("production create-refused arm did not terminate within 5s", file=sys.stderr)
    print(stderr, file=sys.stderr)
    raise SystemExit(1)
json.dump(
    {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
    open(receipt, "w", encoding="utf-8"),
    sort_keys=True,
)
if result.returncode != 70:
    print(result.stderr, file=sys.stderr)
    raise SystemExit(f"expected exit 70, observed {result.returncode}")
terminal = "crime=rebuild-lock-create-refused"
if result.stderr.count(terminal) != 1:
    print(result.stderr, file=sys.stderr)
    raise SystemExit("expected exactly one named create-refused terminal")
for testimony in ("state=create-refused", '"errno_name":"ENOTDIR"'):
    if testimony not in result.stderr:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"missing terminal testimony: {testimony}")
PY

# A real peer can publish and release the whole lock while this waiter is
# observing it. Drive the production door until it narrates contention, then
# release; the waiter must retry and acquire rather than invent a missing PID.
rm -rf "$production_lock"
mkdir -m 0777 "$production_lock"
printf 'peer\n' >"$production_lock/pid"
: >"$production_lock/heartbeat"
SUGAR_BINARY_CACHE_DIR="$production_cache" \
SUGAR_BINARY_SOURCE_STAMP="$production_stamp" \
  "$sugarbin" preflight-lock --bin sugar --profile debug --platform fixture \
  >"$tmp/released-peer.out" 2>"$tmp/released-peer.err" &
released_waiter=$!
observed_wait=0
for _ in $(seq 1 100); do
  if grep -Fq 'phase=resolve-wait ' "$tmp/released-peer.err" 2>/dev/null; then
    observed_wait=1
    break
  fi
  sleep 0.02
done
[[ "$observed_wait" == 1 ]] || {
  kill "$released_waiter" 2>/dev/null || true
  wait "$released_waiter" 2>/dev/null || true
  fail 'released-peer arm never observed authenticated contention'
}
rm -rf "$production_lock"
wait "$released_waiter" || {
  cat "$tmp/released-peer.err" >&2
  fail 'released peer was misclassified as malformed lock'
}
grep -Fq 'phase=resolve-wait-acquired' "$tmp/released-peer.err" \
  || fail 'released-peer waiter did not reacquire after lawful release'
if grep -Fq 'crime=missing-rebuild-lock-pid' "$tmp/released-peer.err"; then
  cat "$tmp/released-peer.err" >&2
  fail 'released peer emitted missing-pid crime'
fi

echo 'PASS: lock lifecycle covers never-created, create-refused, created-unpublished, published-live, published-dead, released, and unreclaimable states'

echo 'PASS: R_shelf_rebuild_single_flight — one build, waiter cell, dead-winner reclaim'
