#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:?usage: sugarbin_wrapper_compat.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fixture="$tmp/repo"
mkdir -p "$fixture/bin"
cp "$repo_root/bin/bcargo" "$repo_root/bin/brun" "$fixture/bin/"
git -C "$fixture" init -q

if grep -Fq "SUGAR_BUILD_GIT_HEAD" \
  "$repo_root/bin/sugarbin" "$repo_root/bin/bcargo" "$repo_root/bin/brun"; then
  echo "obsolete SUGAR_BUILD_GIT_HEAD remains in the execution broker or wrappers" >&2
  exit 1
fi

cat >"$fixture/bin/sugarbin" <<'SH'
#!/usr/bin/env bash
printf x >>"$SUGARBIN_WRAPPER_COUNT"
printf '%s\0' "$@" >"$SUGARBIN_WRAPPER_LOG"
exit "${SUGARBIN_WRAPPER_STATUS:-0}"
SH
chmod +x "$fixture/bin/sugarbin"
cat >"$fixture/bin/ssh" <<'SH'
#!/usr/bin/env bash
exit 97
SH
chmod +x "$fixture/bin/ssh"

assert_args() {
  python3 - "$SUGARBIN_WRAPPER_LOG" "$@" <<'PY'
import sys
from pathlib import Path

actual = Path(sys.argv[1]).read_bytes().split(b"\0")
if actual[-1:] == [b""]:
    actual.pop()
expected = [arg.encode() for arg in sys.argv[2:]]
if actual != expected:
    raise SystemExit(f"argument mismatch:\nactual={actual!r}\nexpected={expected!r}")
PY
}

export SUGARBIN_WRAPPER_LOG="$tmp/args.log"
export SUGARBIN_WRAPPER_COUNT="$tmp/count.log"
: >"$SUGARBIN_WRAPPER_COUNT"
status=0
(cd "$fixture" && BCARGO_SSH="$fixture/bin/ssh" SUGARBIN_WRAPPER_STATUS=29 bin/bcargo --sync-bin sugar test -p sugar-cli) || status=$?
[[ "$status" -eq 29 ]] || { echo "bcargo returned $status, expected 29" >&2; exit 1; }
[[ "$(wc -c <"$SUGARBIN_WRAPPER_COUNT" | tr -d ' ')" -eq 1 ]] || { echo "bcargo invoked sugarbin more than once" >&2; exit 1; }
assert_args cargo --host bx --sync-bin sugar -- test -p sugar-cli

: >"$SUGARBIN_WRAPPER_COUNT"
status=0
(cd "$fixture" && SUGARBIN_WRAPPER_STATUS=31 bin/brun --path-prefix /x --env TOKEN -- true) || status=$?
[[ "$status" -eq 31 ]] || { echo "brun returned $status, expected 31" >&2; exit 1; }
[[ "$(wc -c <"$SUGARBIN_WRAPPER_COUNT" | tr -d ' ')" -eq 1 ]] || { echo "brun invoked sugarbin more than once" >&2; exit 1; }
assert_args run --host bx --path-prefix /x --env TOKEN -- true

echo "PASS: sugarbin wrapper compatibility contract"
