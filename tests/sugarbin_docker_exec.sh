#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_docker_exec.sh REPO_ROOT}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"; : >"$tmp/ssh.log"; : >"$tmp/rsync.log"; : >"$tmp/docker.log"
fail() { echo "FAIL: $*" >&2; exit 1; }

cat >"$tmp/bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_SSH_LOG"
if [[ "$*" == *"wslpath -w"* ]]; then
  path="${*#*wslpath -w \'}"; path="${path%%\'*}"
  printf 'C:\\wsl%s\r\n' "${path//\//\\}"
  exit 0
fi
case "$*" in
  *"'docker' 'run'"*)
    printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
    [[ "$*" != *CHILD_EXIT_43* ]] || exit 43
    ;;
esac
exit 0
SH
cat >"$tmp/bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_RSYNC_LOG"
exit 0
SH
cat >"$tmp/bin/docker" <<'SH'
#!/usr/bin/env bash
echo local-docker >>"$FAKE_DOCKER_LOG"
exit 99
SH
chmod +x "$tmp/bin/"*

run() {
  (cd "$repo/implementations/python" && PATH="$tmp/bin:$PATH" \
    BCARGO_SSH="$tmp/bin/ssh" BCARGO_RSYNC="$tmp/bin/rsync" \
    BCARGO_REMOTE_ROOT=/home/tsavo/remote/sugar-bcargo-example \
    BCARGO_REAP_DAYS=0 SUGAR_BX_PYTHON_ENV=0 \
    FAKE_SSH_LOG="$tmp/ssh.log" FAKE_RSYNC_LOG="$tmp/rsync.log" \
    FAKE_DOCKER_LOG="$tmp/docker.log" "$repo/bin/sugarbin" "$@")
}

core="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:core)"
core_ref="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])' <<<"$core")"
[[ "$core_ref" == *@sha256:* ]] || fail "core did not resolve immutably"
# Task 7 publishes solver-z3. Exercise its distinct closure selection against a
# fixture contract without making a false capability claim in the live contract.
cp "$repo/sugar-build.toml" "$tmp/solver-contract.toml"
cat >>"$tmp/solver-contract.toml" <<'TOML'
[images."core,solver-z3"]
reference = "python@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
TOML
solver_ref="$(python3 - "$repo" "$tmp/solver-contract.toml" <<'PY'
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]) / "tools/sugar-build/contract.py"
spec = importlib.util.spec_from_file_location("sugar_build_contract", path)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
print(module.resolve_environment("docker:solver-z3", sys.argv[2])["image"])
PY
)"
[[ "$solver_ref" == *@sha256:* && "$solver_ref" != "$core_ref" ]] || fail "solver closure did not select its own fixture image"

run run --host bx --env docker:core --needs sugar -- sh -c 'echo hit' >/dev/null
line="$(tail -1 "$tmp/docker.log")"
[[ "$line" == *"'$core_ref'"* ]] || fail "wrong core image: $line"
[[ "$line" == *"--workdir' '/workspace/sugar/implementations/python'"* ]] || fail "wrong workdir"
[[ "$line" == *"dst=/workspace/sugar"* ]] || fail "workspace mount missing"
[[ "$line" == *"src=C:"* ]] || fail "WSL bind source was not translated"
[[ "$line" == *"dst=/opt/sugar/bin,readonly"* ]] || fail "artifact mount not read-only"
[[ "$line" == *"required-artifacts.json,readonly"* ]] || fail "stamp mount not read-only"
[[ "$line" == *"SUGAR_BIN=/opt/sugar/bin/sugar"* ]] || fail "SUGAR_BIN not injected"
[[ "$line" == *"PATH=/opt/sugar/bin:"* ]] || fail "artifact PATH is not first"
[[ "$line" != *docker.sock* ]] || fail "Docker socket leaked into task"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 1 ]] || fail "hit child not executed exactly once"

run run --host bx --env docker:core -- sh -c 'echo miss' >/dev/null
[[ "$(tail -1 "$tmp/docker.log")" == *"'$core_ref'"* ]] || fail "wrong miss image"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 2 ]] || fail "miss child not executed exactly once"

status=0
run run --host bx --env docker:core -- sh -c CHILD_EXIT_43 >/dev/null || status=$?
[[ "$status" == 43 ]] || fail "child exit was $status, want 43"

: >"$tmp/docker.log"
(cd "$repo" && PATH="$tmp/bin:$PATH" FAKE_DOCKER_LOG="$tmp/docker.log" "$repo/bin/sugarbin" run --host local --env ambient -- true)
run run --host bx --env ambient --no-python-env -- true >/dev/null
[[ ! -s "$tmp/docker.log" ]] || fail "ambient route invoked Docker"

echo "PASS: sugarbin Docker execution contract"
