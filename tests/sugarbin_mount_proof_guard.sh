#!/usr/bin/env bash
set -euo pipefail

# Twin for #5914: WSL2 bind mounts on battleaxe can start successfully and
# still be empty or point at the wrong tree, because Docker Desktop's engine
# runs in a separate WSL distro and silently mounts an empty directory for a
# plain Linux path. That produces plausible-looking output with no error.
# tools/sugar-build/entrypoint.sh must prove the mounted workspace matches
# what the caller synced before anything else runs -- including before the
# toolchain contract checks -- and must fail LOUDLY, never a quiet zero, when
# it does not.

repo="${1:?usage: sugarbin_mount_proof_guard.sh REPO_ROOT}"
entrypoint="$repo/tools/sugar-build/entrypoint.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

workspace="$tmp/workspace/sugar"
mkdir -p "$workspace"

# 1. Empty mount: no proof file at all (the exact WSL2 empty-bind-mount
#    shape). The container must refuse before running the payload.
status=0
SUGAR_BX_MOUNT_PROOF="expected-token" \
  SUGAR_BX_MOUNT_PROOF_FILE="$workspace/.bcargo-mount-proof" \
  bash "$entrypoint" sh -c 'echo "measured $(ls "'"$workspace"'" | wc -l) files" >"'"$tmp"'/empty-mount.out"' \
  2>"$tmp/empty-mount.err" || status=$?
[[ "$status" == 70 ]] || fail "empty mount did not fail loudly (status=$status)"
[[ ! -e "$tmp/empty-mount.out" ]] || fail "empty mount still produced a measurement output"
grep -Fq 'crime=empty-or-stale-bind-mount' "$tmp/empty-mount.err" \
  || fail "empty mount error is not named: $(cat "$tmp/empty-mount.err")"

# 2. Wrong/stale mount: a proof file exists but does not match what this run
#    expects (a different checkout mounted at the same path).
printf '%s' "some-other-checkouts-token" >"$workspace/.bcargo-mount-proof"
status=0
SUGAR_BX_MOUNT_PROOF="expected-token" \
  SUGAR_BX_MOUNT_PROOF_FILE="$workspace/.bcargo-mount-proof" \
  bash "$entrypoint" sh -c 'echo measured >"'"$tmp"'/wrong-mount.out"' \
  2>"$tmp/wrong-mount.err" || status=$?
[[ "$status" == 70 ]] || fail "wrong mount did not fail loudly (status=$status)"
[[ ! -e "$tmp/wrong-mount.out" ]] || fail "wrong mount still produced a measurement output"
grep -Fq 'crime=empty-or-stale-bind-mount' "$tmp/wrong-mount.err" \
  || fail "wrong mount error is not named: $(cat "$tmp/wrong-mount.err")"
grep -Fq 'expected=expected-token' "$tmp/wrong-mount.err" || fail "diagnostic omits expected token"
grep -Fq 'actual=some-other-checkouts-token' "$tmp/wrong-mount.err" || fail "diagnostic omits actual token"

# 3. Matching proof: the guard must get out of the way and let the run
#    proceed to the next gate (the toolchain contract), not silently swallow
#    a real, correctly-mounted workspace. We do not have the pinned
#    toolchain available in this unit-test environment, so the run is
#    expected to fail at contract_mismatch instead -- proving the mount
#    guard itself did not fire is exactly what discriminates this case from
#    cases 1 and 2 above.
printf '%s' "expected-token" >"$workspace/.bcargo-mount-proof"
status=0
SUGAR_BX_MOUNT_PROOF="expected-token" \
  SUGAR_BX_MOUNT_PROOF_FILE="$workspace/.bcargo-mount-proof" \
  bash "$entrypoint" sh -c 'echo measured >"'"$tmp"'/ok-mount.out"' \
  2>"$tmp/ok-mount.err" || status=$?
! grep -Fq 'crime=empty-or-stale-bind-mount' "$tmp/ok-mount.err" \
  || fail "matching mount proof was still rejected: $(cat "$tmp/ok-mount.err")"

# 4. No proof requested at all (SUGAR_BX_MOUNT_PROOF unset): the guard is
#    opt-in per run so ad-hoc/non-bx uses of the image are unaffected.
status=0
bash "$entrypoint" sh -c 'echo measured >"'"$tmp"'/unguarded.out"' \
  2>"$tmp/unguarded.err" || status=$?
! grep -Fq 'crime=empty-or-stale-bind-mount' "$tmp/unguarded.err" \
  || fail "guard fired without a requested mount proof"

echo "PASS: sugarbin mount-proof guard contract"
