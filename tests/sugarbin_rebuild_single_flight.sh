#!/usr/bin/env bash
# R_shelf_rebuild_single_flight teeth.
# Concurrent matrix resolvers must not each cargo-build the same stamp.
# The publish race only dedupes the CAS cell AFTER waste; this lock prevents waste.
set -euo pipefail

repo="${1:?usage: sugarbin_rebuild_single_flight.sh REPO_ROOT}"
sugarbin="$repo/bin/sugarbin"
[[ -x "$sugarbin" ]] || { echo "missing $sugarbin" >&2; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# Static: ONE door shapes present on the miss→rebuild path.
grep -Fq 'acquire_rebuild_single_flight' "$sugarbin" || fail 'missing acquire_rebuild_single_flight'
grep -Fq 'release_rebuild_single_flight' "$sugarbin" || fail 'missing release_rebuild_single_flight'
grep -Fq 'rebuild single-flight: peer published' "$sugarbin" || fail 'missing double-check after lock'
grep -Fq '.rebuild-locks' "$sugarbin" || fail 'missing lock directory under cache'

# Lock key must include stamp + bin + platform + profile (not a global mutex).
acquire_body="$(sed -n '/^acquire_rebuild_single_flight()/,/^release_rebuild_single_flight()/p' "$sugarbin")"
grep -Fq 'stamp_for_filename "$stamp"' <<<"$acquire_body" || fail 'lock key does not include stamp'
grep -Fq 'bin_name' <<<"$acquire_body" || fail 'lock key does not include bin_name'
grep -Fq 'platform_key' <<<"$acquire_body" || fail 'lock key does not include platform'
# Atomic mkdir is the portable lock (not a short-lived flock child).
grep -Fq 'mkdir "$lockdir"' <<<"$acquire_body" || fail 'lock must use atomic mkdir'
if grep -Fq 'heavy-measurement' <<<"$acquire_body"; then
  fail 'rebuild single-flight must not use the deleted heavy-measurement lease'
fi

# main() miss path: acquire before build_from_source, release on every exit.
main_body="$(sed -n '/^main()/,/^if \[\[ -n "\$artifact_subcommand" \]\]/p' "$sugarbin")"
acquire_line="$(grep -n 'acquire_rebuild_single_flight' <<<"$main_body" | head -1 | cut -d: -f1)"
build_line="$(grep -n 'build_from_source' <<<"$main_body" | head -1 | cut -d: -f1)"
[[ -n "$acquire_line" && -n "$build_line" ]] || fail 'main missing acquire or build_from_source'
[[ "$acquire_line" -lt "$build_line" ]] || fail 'acquire must precede build_from_source'
n_release=$(grep -c 'release_rebuild_single_flight' <<<"$main_body" || true)
# peer-hit, verify-fail, publish-fail, success — at least three release sites.
[[ "$n_release" -ge 3 ]] || fail "main must release lock on every exit (found $n_release)"

# Dynamic: two processes cannot hold the same mkdir-lock simultaneously.
tmp="$(mktemp -d "${TMPDIR:-/tmp}/shelf-sflight.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
lock="$tmp/demo.lock"
# Holder keeps the lock for 2s via mkdir.
(
  mkdir "$lock"
  echo $$ >"$lock/pid"
  sleep 2
  rm -rf "$lock"
) &
holder=$!
sleep 0.2
start=$(date +%s)
# Waiter spins until mkdir succeeds (same algorithm as acquire).
while ! mkdir "$lock" 2>/dev/null; do
  if [[ -f "$lock/pid" ]]; then
    h="$(tr -d '[:space:]' <"$lock/pid" 2>/dev/null || true)"
    if [[ -n "$h" ]] && ! kill -0 "$h" 2>/dev/null; then
      rm -rf "$lock" 2>/dev/null || true
    fi
  fi
  sleep 0.1
done
rm -rf "$lock"
end=$(date +%s)
wait "$holder" || true
elapsed=$((end - start))
[[ "$elapsed" -ge 1 ]] || fail "mkdir lock did not serialize waiters (elapsed=${elapsed}s)"
echo "PASS: dynamic mkdir-lock serialization (${elapsed}s wait)"

echo 'PASS: R_shelf_rebuild_single_flight — stamp-keyed lock before rebuild, double-check after'
