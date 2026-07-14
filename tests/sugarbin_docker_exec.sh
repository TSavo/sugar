#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_docker_exec.sh REPO_ROOT}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"; : >"$tmp/ssh.log"; : >"$tmp/rsync.log"; : >"$tmp/docker.log"
fail() { echo "FAIL: $*" >&2; exit 1; }

dockerfile="$(cat "$repo/tools/sugar-build/Dockerfile")"
[[ "$dockerfile" == *'PYRIGHT_PYTHON_ENV_DIR=/opt/pyright/nodeenv'* ]] || fail "Pyright runtime location is not retained"
[[ "$dockerfile" == *'PYRIGHT_PYTHON_GLOBAL_NODE=0'* ]] || fail "Pyright can escape to an ambient Node runtime"
[[ "$dockerfile" == *'PYRIGHT_NODE_VERSION=26.5.0'* ]] || fail "Pyright Node bootstrap is not version-pinned"
[[ "$dockerfile" == *'PYRIGHT_PYTHON_NODE_VERSION="${PYRIGHT_NODE_VERSION}" python -m pyright --version'* ]] || fail "Pyright runtime is not bootstrapped during the image build"
[[ "$dockerfile" == *'/opt/pyright/node-version'* ]] || fail "Pyright Node identity is not recorded"
for stage in python-test solver-z3 python-lift-closure examples-closure; do
  [[ "$dockerfile" == *"AS $stage"* ]] || fail "missing additive $stage stage"
done
[[ "$dockerfile" == *'z3 --version'* ]] || fail "z3 stage has no smoke command"
[[ "$dockerfile" == *'import numpy, pandas'* ]] || fail "scientific stage has no import smoke"
[[ "$dockerfile" == *'node --version'* && "$dockerfile" == *'pnpm --version'* ]] || fail "node stage has no smoke commands"
[[ "$dockerfile" == *'vampire --version'* ]] || fail "vampire stage has no smoke command"
entrypoint="$(cat "$repo/tools/sugar-build/entrypoint.sh")"
[[ "$entrypoint" == *'/opt/pyright/node-version'* ]] || fail "entrypoint does not verify the embedded Pyright runtime"

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

explain="$(run explain --host bx --task python-unit)"
python_test_ref="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:python-test | python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])')"
[[ "$explain" == *"docker_image=$python_test_ref"* ]] || fail "explain omitted resolved immutable Docker image"

run run --host bx --task python-unit -- -q >/dev/null
line="$(tail -1 "$tmp/docker.log")"
[[ "$line" == *"'$python_test_ref'"* ]] || fail "python-unit did not select managed test closure"
[[ "$line" == *"'python' '-m' 'pytest' '-q'"* ]] || fail "python-unit command did not always execute"
: >"$tmp/docker.log"
solver_ref="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:solver-z3 | python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])')"
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
[[ "$line" == *"/opt/java/bin"* ]] || fail "managed Java toolchain missing from Docker PATH"
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
