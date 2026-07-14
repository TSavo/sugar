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
    BCARGO_REAP_DAYS=0 \
    FAKE_SSH_LOG="$tmp/ssh.log" FAKE_RSYNC_LOG="$tmp/rsync.log" \
    FAKE_DOCKER_LOG="$tmp/docker.log" "$repo/bin/sugarbin" "$@")
}

core="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:core)"
core_ref="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])' <<<"$core")"
[[ "$core_ref" == *@sha256:* ]] || fail "core did not resolve immutably"

explain="$(run explain --host bx --task python-unit)"
python_test_ref="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:python-test | python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])')"
[[ "$explain" == *"docker_image=$python_test_ref"* ]] || fail "explain omitted resolved immutable Docker image"
[[ "$explain" == *"platform=linux-x86_64"* ]] || fail "bx explain reported caller platform"
[[ "$explain" == *"network=none"* ]] || fail "python-unit network policy missing from explain"

: >"$tmp/rsync.log"
status=0
run explain --host bx --platform darwin-x86_64 --task python-unit >"$tmp/platform.out" 2>"$tmp/platform.err" || status=$?
[[ "$status" == 2 ]] || fail "bx accepted Darwin platform"
grep -Fq 'available=linux-x86_64' "$tmp/platform.err" || fail "bx platform diagnostic missing"
[[ ! -s "$tmp/rsync.log" ]] || fail "bx platform rejection happened after sync"

run run --host bx --task python-unit -- -q >/dev/null
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 2 ]] || fail "managed artifact build and task did not each run once"
build_line="$(head -1 "$tmp/docker.log")"
line="$(tail -1 "$tmp/docker.log")"
[[ "$build_line" == *"'$core_ref'"* && "$build_line" == *"bin/sugarbin"* ]] || fail "artifact was not resolved inside managed core: $build_line"
[[ "$build_line" == *"dst=/root/.cache/sugar/binaries"* ]] || fail "managed builder omitted persistent verified cache"
[[ "$build_line" == *"CARGO_TARGET_DIR=/managed-target"* ]] || fail "managed builder reused ambient Cargo target"
[[ "$build_line" == *"SUGAR_BINARY_TARGET_ROOT=/managed-target"* ]] || fail "managed manifest root diverges from Cargo target"
[[ "$build_line" == *"dst=/managed-target"* ]] || fail "managed target cache was not mounted"
[[ "$build_line" != *"SUGAR_BINARY_TARGET_ROOT=/workspace/sugar/implementations/rust/target"* ]] || fail "ambient target entered managed builder"
if grep -F 'bin/sugarbin --platform' "$tmp/ssh.log" | grep -Fvq "'docker' 'run'"; then
  fail "artifact identity was recomputed in ambient bx"
fi
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
[[ "$line" != *"--env' 'SUGAR_BIN="* ]] || fail "orchestrator forged SUGAR_BIN before manifest verification"
[[ "$entrypoint" == *'export SUGAR_BIN=/opt/sugar/bin/sugar'* ]] || fail "entrypoint does not inject verified sugar"
[[ "$line" == *"PATH=/opt/sugar/bin:"* ]] || fail "artifact PATH is not first"
[[ "$line" == *"/opt/java/bin"* ]] || fail "managed Java toolchain missing from Docker PATH"
[[ "$line" != *docker.sock* ]] || fail "Docker socket leaked into task"
[[ "$line" != *"--network' 'none"* ]] || fail "ad-hoc Docker command was forced offline"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 2 ]] || fail "managed build/task count wrong"

run run --host bx --env docker:core -- sh -c 'echo miss' >/dev/null
[[ "$(tail -1 "$tmp/docker.log")" == *"'$core_ref'"* ]] || fail "wrong miss image"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 3 ]] || fail "zero-artifact child did not execute exactly once"

status=0
run run --host bx --env docker:core -- sh -c CHILD_EXIT_43 >/dev/null || status=$?
[[ "$status" == 43 ]] || fail "child exit was $status, want 43"

: >"$tmp/docker.log"
(cd "$repo" && PATH="$tmp/bin:$PATH" FAKE_DOCKER_LOG="$tmp/docker.log" "$repo/bin/sugarbin" run --host local --env ambient -- true)
run run --host bx --env ambient -- true >/dev/null
[[ ! -s "$tmp/docker.log" ]] || fail "ambient route invoked Docker"

# An explicit ambient task stays ambient; omission alone opts a bx task into
# its declared managed closure.
: >"$tmp/docker.log"; : >"$tmp/ssh.log"
run run --host bx --env ambient --task python-unit -- -q >/dev/null
[[ ! -s "$tmp/docker.log" ]] || fail "explicit ambient task was forced into Docker"
grep -Fq "pytest" "$tmp/ssh.log" || fail "ambient task command did not execute"

# rust-unit declares no injected Sugar binaries. Its container must not receive
# a false SUGAR_BIN or an empty artifact manifest.
: >"$tmp/docker.log"
run run --host bx --task rust-unit -- --help >/dev/null
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 1 ]] || fail "zero-binary task ran artifact builder"
line="$(tail -1 "$tmp/docker.log")"
[[ "$line" != *"SUGAR_BIN="* ]] || fail "zero-binary task received SUGAR_BIN"
[[ "$line" != *"required-artifacts.json"* ]] || fail "zero-binary task received empty artifact manifest"
[[ "$line" != *"--network' 'none"* ]] || fail "Cargo task was forced offline without a vendored registry"

examples="$(run explain --host bx --task examples-gate)"
[[ "$examples" == *"network=required"* ]] || fail "examples-gate network requirement not explicit"

echo "PASS: sugarbin Docker execution contract"
