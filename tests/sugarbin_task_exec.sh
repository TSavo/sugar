#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_task_exec.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fixture="$tmp/repo"
mkdir -p "$fixture/bin/lib" "$fixture/tools/sugar-build"
cp "$repo/bin/sugarbin" "$fixture/bin/"
cp "$repo/bin/lib/sugar-exec.sh" "$fixture/bin/lib/"
cp "$repo/tools/sugar-build/contract.py" "$fixture/tools/sugar-build/"

cat >"$tmp/record" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -s "$TASK_COUNT" ]] || count="$(cat "$TASK_COUNT")"
printf '%s\n' "$((count + 1))" >"$TASK_COUNT"
printf '%s\n' "$@" >"$TASK_ARGS"
SH
chmod +x "$tmp/record"

cat >"$fixture/sugar-build.toml" <<EOF
schema = 1

[tools]

[capabilities.core]
depends = []

[tasks.record]
capabilities = ["core"]
binaries = []
command = ["$tmp/record", "default"]
network = "none"
EOF

export TASK_COUNT="$tmp/count"
export TASK_ARGS="$tmp/args"
: >"$TASK_COUNT"

"$fixture/bin/sugarbin" run --task record
[[ "$(cat "$TASK_COUNT")" == 1 ]]
[[ "$(cat "$TASK_ARGS")" == default ]]

"$fixture/bin/sugarbin" run --task record -- appended "two words"
[[ "$(cat "$TASK_COUNT")" == 2 ]]
printf 'default\nappended\ntwo words\n' >"$tmp/expected-args"
cmp "$tmp/expected-args" "$TASK_ARGS"

status=0
"$fixture/bin/sugarbin" run >"$tmp/no-command.out" 2>"$tmp/no-command.err" || status=$?
[[ "$status" == 2 ]]
[[ "$(cat "$TASK_COUNT")" == 2 ]]
grep -Fq "run requires -- followed by a command" "$tmp/no-command.err"

status=0
"$fixture/bin/sugarbin" run --env docker -- "$tmp/record" forbidden \
  >"$tmp/docker.out" 2>"$tmp/docker.err" || status=$?
[[ "$status" == 2 ]]
[[ "$(cat "$TASK_COUNT")" == 2 ]]
grep -Fq "empty capability" "$tmp/docker.err"

echo "PASS: sugarbin named task execution contract"
