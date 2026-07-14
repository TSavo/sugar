#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_local_exec.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export SUGARBIN_TEST_TMP="$tmp"
: >"$tmp/count"
: >"$tmp/ssh.log"
: >"$tmp/docker.log"

cat >"$tmp/record" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -s "$SUGARBIN_TEST_TMP/count" ]] || count="$(cat "$SUGARBIN_TEST_TMP/count")"
printf '%s\n' "$((count + 1))" >"$SUGARBIN_TEST_TMP/count"
{
  printf 'cwd=%s\n' "$PWD"
  printf 'arg=%s\n' "$@"
} >"$SUGARBIN_TEST_TMP/log"
EOF

cat >"$tmp/exit-37" <<'EOF'
#!/usr/bin/env bash
exit 37
EOF

cat >"$tmp/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_TEST_TMP/ssh.log"
EOF

cat >"$tmp/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_TEST_TMP/docker.log"
EOF
chmod +x "$tmp/record" "$tmp/exit-37" "$tmp/ssh" "$tmp/docker"
export PATH="$tmp:$PATH"

"$repo/bin/sugarbin" run -- "$tmp/record" one "two words"
[[ "$(cat "$tmp/count")" == 1 ]]
grep -Fx "cwd=$PWD" "$tmp/log"
grep -Fx "arg=one" "$tmp/log"
grep -Fx "arg=two words" "$tmp/log"

set +e
"$repo/bin/sugarbin" run -- "$tmp/exit-37"
status=$?
set -e
[[ "$status" == 37 ]]

platform="$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m | tr '[:upper:]' '[:lower:]')"
case "$platform" in
  *-amd64) platform="${platform%-amd64}-x86_64" ;;
  *-x64) platform="${platform%-x64}-x86_64" ;;
  *-aarch64) platform="${platform%-aarch64}-arm64" ;;
esac
case "$platform" in
  darwin-*) conflicting="linux-x86_64" ;;
  *) conflicting="darwin-arm64" ;;
esac

set +e
"$repo/bin/sugarbin" run --platform "$conflicting" -- "$tmp/record" forbidden \
  >"$tmp/conflict.out" 2>"$tmp/conflict.err"
status=$?
set -e
[[ "$status" == 2 ]]
[[ "$(cat "$tmp/count")" == 1 ]]
grep -F "unsupported execution route" "$tmp/conflict.err"

! grep -q . "$tmp/ssh.log"
! grep -q . "$tmp/docker.log"
