#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:?usage: bpytest_authenticated_wrapper.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fixture="$tmp/repo"
mkdir -p "$fixture/bin"
cp "$repo_root/bin/bpytest" "$fixture/bin/"
git -C "$fixture" init -q

cat >"$fixture/bin/sugarbin" <<'SH'
#!/usr/bin/env bash
printf '%s\0' "$@" >"$SUGARBIN_WRAPPER_LOG"
printf '%s' "${PYTHONUNBUFFERED:-}" >"$SUGARBIN_WRAPPER_ENV_LOG"
exit "${SUGARBIN_WRAPPER_STATUS:-0}"
SH
chmod +x "$fixture/bin/sugarbin"

export SUGARBIN_WRAPPER_LOG="$tmp/args.log"
export SUGARBIN_WRAPPER_ENV_LOG="$tmp/env.log"

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

status=0
(cd "$fixture" && SUGARBIN_WRAPPER_STATUS=37 bin/bpytest -q tests/unit) || status=$?
[[ "$status" -eq 37 ]] || { echo "bpytest returned $status, expected 37" >&2; exit 1; }
assert_args run --host bx --task authenticated-python-lift -- -q tests/unit

status=0
(cd "$fixture" && SUGARBIN_WRAPPER_STATUS=41 bin/bpytest -u -q tests/unit) || status=$?
[[ "$status" -eq 41 ]] || { echo "bpytest -u returned $status, expected 41" >&2; exit 1; }
[[ "$(cat "$SUGARBIN_WRAPPER_ENV_LOG")" == 1 ]] || { echo "bpytest -u did not set PYTHONUNBUFFERED=1" >&2; exit 1; }
assert_args run --host bx --env PYTHONUNBUFFERED --task authenticated-python-lift -- -q tests/unit

echo "PASS: authenticated bpytest wrapper"
