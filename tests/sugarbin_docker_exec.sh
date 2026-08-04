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
[[ "$explain" == *"profile=release"* ]] || fail "default artifact profile missing from explain"

status=0
run explain --host bx --env docker:core --task python-unit >"$tmp/closure.out" 2>"$tmp/closure.err" || status=$?
[[ "$status" == 2 ]] || fail "task accepted an insufficient explicit Docker closure"
grep -Fq 'missing capabilities: python-test' "$tmp/closure.err" || fail "insufficient closure diagnostic missing"

debug_explain="$(run explain --host bx --profile debug --task python-unit)"
[[ "$debug_explain" == *"profile=debug"* ]] || fail "debug artifact profile was not retained"

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
[[ "$build_line" == *"dst=/root/.cache/sugar/binary-shelf-v2,readonly"* ]] || fail "ordinary managed resolution shelf is missing or writable"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_SHELF_READ_ONLY=1'"* ]] || fail "ordinary managed resolution did not carry read-only shelf authority"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_ALLOW_BUILD=0'"* ]] || fail "ordinary managed resolution retained an implicit build fallback"
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
SUGAR_BINARY_ALLOW_BUILD=0 run run --host bx --env SUGAR_BINARY_ALLOW_BUILD --task python-unit -- -q >/dev/null
build_line="$(head -1 "$tmp/docker.log")"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_ALLOW_BUILD=0'"* ]] || fail "managed artifact resolver did not inherit fail-fast binary policy: $build_line"
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
[[ "$line" == *"dst=/root/.cache/sugar/binary-shelf-v2,readonly"* ]] || fail "managed task cannot consume exact shelf payloads"
[[ "$line" == *"'--env' 'SUGAR_BINARY_SHELF_READ_ONLY=1'"* ]] || fail "managed task did not carry read-only shelf authority"
[[ "$line" == *"'--env' 'SUGAR_BINARY_PUBLISH=0'"* ]] || fail "read-only managed task retained implicit filesystem-shelf publish authority"
[[ "$line" == *"required-artifacts.json,readonly"* ]] || fail "stamp mount not read-only"
[[ "$line" != *"--env' 'SUGAR_BIN="* ]] || fail "orchestrator forged SUGAR_BIN before manifest verification"
[[ "$entrypoint" == *'export SUGAR_BIN=/opt/sugar/bin/sugar'* ]] || fail "entrypoint does not inject verified sugar"
[[ "$line" == *"PATH=/opt/sugar/bin:"* ]] || fail "artifact PATH is not first"
[[ "$line" == *"/opt/java/bin"* ]] || fail "managed Java toolchain missing from Docker PATH"
[[ "$line" != *docker.sock* ]] || fail "Docker socket leaked into task"
[[ "$line" != *"--network' 'none"* ]] || fail "ad-hoc Docker command was forced offline"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 2 ]] || fail "managed build/task count wrong"

# Shelf mount authority belongs to the transport, never to caller-forwarded
# environment. A payload cannot turn the read-only task mount into writable
# recovery authority by forwarding a contradictory value.
: >"$tmp/docker.log"
SUGAR_BINARY_SHELF_READ_ONLY=0 run run --host bx --env docker:core \
  --env SUGAR_BINARY_SHELF_READ_ONLY -- sh -c 'echo authority' >/dev/null
line="$(tail -1 "$tmp/docker.log")"
[[ "$line" == *"'--env' 'SUGAR_BINARY_SHELF_READ_ONLY=1'"* ]] || fail "task lost transport-owned read-only shelf authority"
[[ "$line" != *"'--env' 'SUGAR_BINARY_SHELF_READ_ONLY=0'"* ]] || fail "task forwarded forged writable shelf authority"

: >"$tmp/docker.log"
run build --host bx --env docker:core --profile debug --needs sugar >/dev/null
build_line="$(head -1 "$tmp/docker.log")"
[[ "$build_line" == *"--profile"* && "$build_line" == *"debug"* ]] || fail "managed artifact profile did not reach the core builder"
: >"$tmp/docker.log"

SUGAR_BINARY_ALLOW_BUILD=1 SUGAR_BINARY_PUBLISH=1 SUGAR_BINARY_REQUIRE_PUBLISH=1 \
  run build --host bx --env docker:core \
    --env SUGAR_BINARY_ALLOW_BUILD --env SUGAR_BINARY_PUBLISH \
    --env SUGAR_BINARY_REQUIRE_PUBLISH --needs sugar >/dev/null
build_line="$(head -1 "$tmp/docker.log")"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_ALLOW_BUILD=1'"* ]] || fail "explicit managed publisher lost build authority"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_PUBLISH=1'"* ]] || fail "explicit managed publisher lost publish authority"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_REQUIRE_PUBLISH=1'"* ]] || fail "explicit managed publisher did not require a complete shelf cell"
[[ "$build_line" != *"SUGAR_BINARY_PUBLISH=0 bin/sugarbin"* ]] || fail "managed build script overrode explicit publish authority"
[[ "$build_line" == *"dst=/root/.cache/sugar/binary-shelf-v2"* && "$build_line" != *"dst=/root/.cache/sugar/binary-shelf-v2,readonly"* ]] || fail "explicit managed publisher did not receive the writable shelf"
[[ "$build_line" == *"'--env' 'SUGAR_BINARY_SHELF_READ_ONLY=0'"* ]] || fail "explicit managed publisher retained read-only shelf authority"
: >"$tmp/docker.log"

status=0
SUGAR_BINARY_ALLOW_BUILD=1 SUGAR_BINARY_PUBLISH=1 SUGAR_BINARY_REQUIRE_PUBLISH=1 \
  run run --host bx --env SUGAR_BINARY_ALLOW_BUILD \
    --env SUGAR_BINARY_PUBLISH --env SUGAR_BINARY_REQUIRE_PUBLISH \
    --task python-unit -- -q >"$tmp/run-publish.out" 2>"$tmp/run-publish.err" || status=$?
[[ "$status" == 2 ]] || fail "managed run accepted provisioning authority: status=$status"
grep -Fq 'provisioning authority requires explicit sugarbin build' "$tmp/run-publish.err" || fail "managed run provisioning refusal was not named"
[[ ! -s "$tmp/docker.log" ]] || fail "managed run provisioning refusal happened after Docker"
: >"$tmp/docker.log"

run run --host bx --env docker:core -- sh -c 'echo miss' >/dev/null
[[ "$(tail -1 "$tmp/docker.log")" == *"'$core_ref'"* ]] || fail "wrong miss image"
[[ "$(wc -l <"$tmp/docker.log" | tr -d ' ')" == 1 ]] || fail "zero-artifact child did not execute exactly once"

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

: >"$tmp/docker.log"
run run --host bx --task showcases >/dev/null
showcase_line="$(tail -1 "$tmp/docker.log")"
[[ "$showcase_line" == *"tools/sugar-build/preflight.py"* ]] \
  || fail "managed showcase task omitted pre-subject preflight"
[[ "$showcase_line" == *"make"*"test-showcases"* ]] \
  || fail "managed showcase task lost its declared command"

# Artifact-manifest refusal belongs to the managed entrypoint, after the
# toolchain has authenticated. Exercise that real shell boundary with /opt
# relocated into this test's private root; only absolute fixture paths change.
entrypoint_root="$tmp/entrypoint-root"
entrypoint_under_test="$tmp/entrypoint-under-test.sh"
entrypoint_bin="$tmp/entrypoint-bin"
mkdir -p "$entrypoint_root/opt/sugar/bin" \
  "$entrypoint_root/opt/pyright/nodeenv/bin" "$entrypoint_bin"
python3 - "$repo/tools/sugar-build/entrypoint.sh" \
  "$entrypoint_under_test" "$entrypoint_root" <<'PY'
from pathlib import Path
import sys

source, target, root = map(Path, sys.argv[1:])
target.write_text(source.read_text().replace("/opt/", f"{root}/opt/"))
PY
cat >"$entrypoint_bin/rustc" <<'SH'
#!/usr/bin/env bash
printf 'rustc 1.96.0\n'
SH
cat >"$entrypoint_bin/cargo" <<'SH'
#!/usr/bin/env bash
printf 'cargo 1.96.0\n'
SH
cat >"$entrypoint_bin/black" <<'SH'
#!/usr/bin/env bash
printf 'black 26.5.1\n'
SH
cat >"$entrypoint_bin/b3sum" <<'SH'
#!/usr/bin/env bash
printf 'b3sum 1.8.1\n'
SH
cat >"$entrypoint_bin/python" <<'SH'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf 'Python 3.12.13\n' ;;
  -m) printf 'pyright 1.1.411\n' ;;
  -c) printf 'node 26.5.0\n' ;;
  -) exec "$REAL_PYTHON" "$@" ;;
  *) exec "$REAL_PYTHON" "$@" ;;
esac
SH
printf '#!/usr/bin/env bash\nexit 0\n' \
  >"$entrypoint_root/opt/pyright/nodeenv/bin/node"
printf 'node 26.5.0\n' >"$entrypoint_root/opt/pyright/node-version"
chmod +x "$entrypoint_under_test" "$entrypoint_bin"/* \
  "$entrypoint_root/opt/pyright/nodeenv/bin/node"

manifest="$entrypoint_root/opt/sugar/required-artifacts.json"
printf '{"artifacts":[]}{}\n' >"$manifest"
status=0
PATH="$entrypoint_bin:$PATH" REAL_PYTHON="$(command -v python3)" \
  "$entrypoint_under_test" true >"$tmp/manifest-parse.out" \
  2>"$tmp/manifest-parse.err" || status=$?
[[ "$status" == 70 ]] || fail "malformed artifact manifest status=$status, want 70"
grep -Fq 'crime=artifact-manifest-parse-failed' "$tmp/manifest-parse.err" \
  || fail "malformed artifact manifest did not name parse failure"
grep -Fq "$manifest" "$tmp/manifest-parse.err" \
  || fail "malformed artifact manifest did not name its file"
grep -Fq 'Extra data' "$tmp/manifest-parse.err" \
  || fail "malformed artifact manifest did not retain the parse error"
! grep -Fq 'artifact checksum mismatch' "$tmp/manifest-parse.err" \
  || fail "malformed JSON was misreported as a checksum mismatch"

artifact="$entrypoint_root/opt/sugar/bin/sugar"
printf 'artifact payload\n' >"$artifact"
chmod +x "$artifact"
expected="$(printf '%064d' 0)"
observed="$(python3 - "$artifact" <<'PY'
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
printf '{"artifacts":[{"name":"sugar","sha256":"%s"}]}\n' \
  "$expected" >"$manifest"
status=0
PATH="$entrypoint_bin:$PATH" REAL_PYTHON="$(command -v python3)" \
  "$entrypoint_under_test" true >"$tmp/manifest-checksum.out" \
  2>"$tmp/manifest-checksum.err" || status=$?
[[ "$status" == 70 ]] || fail "artifact checksum mismatch status=$status, want 70"
grep -Fq 'crime=artifact-checksum-mismatch' "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch did not name its cause"
grep -Fq "manifest=$manifest" "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch did not name its manifest"
grep -Fq "artifact=$artifact" "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch did not name its artifact"
grep -Fq "expected=$expected" "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch did not report its expected digest"
grep -Fq "observed=$observed" "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch did not report its observed digest"
! grep -Fq 'crime=artifact-manifest-parse-failed' "$tmp/manifest-checksum.err" \
  || fail "checksum mismatch was misreported as a parse failure"

# Exercise the exact writer script used by the Docker artifact builder. A
# signal after the first artifact has been appended must leave the prior final
# manifest byte-identical; existence alone would admit a truncated replacement.
source "$repo/bin/lib/sugar-bx.sh"
writer_workspace="$tmp/writer-workspace"
writer_out="$tmp/writer-out"
mkdir -p "$writer_workspace/bin" "$writer_out" "$tmp/writer-payloads"
cat >"$writer_workspace/bin/sugarbin" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
binary=""
while (($#)); do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
[[ -n "$binary" ]]
if [[ "$binary" == second && -n "${WRITER_BLOCK_MARKER:-}" ]]; then
  : >"$WRITER_BLOCK_MARKER"
  kill -TERM "$PPID"
  exit 143
fi
printf '%s/%s\n' "$WRITER_PAYLOAD_ROOT" "$binary"
SH
chmod +x "$writer_workspace/bin/sugarbin"
for binary in first second; do
  printf '%s payload\n' "$binary" >"$tmp/writer-payloads/$binary"
  printf '{}\n' >"$tmp/writer-payloads/$binary.sugarbin.json"
done

prior_manifest="$tmp/prior-required-artifacts.json"
printf '{"prior":"evidence"}\n' >"$writer_out/required-artifacts.json"
cp "$writer_out/required-artifacts.json" "$prior_manifest"
writer_script="$(sugar_bx_artifact_build_script \
  first,second release "$writer_workspace" "$writer_out")"
status=0
WRITER_PAYLOAD_ROOT="$tmp/writer-payloads" \
WRITER_BLOCK_MARKER="$tmp/writer-blocked" \
  bash -c "$writer_script" || status=$?
[[ -e "$tmp/writer-blocked" ]] || fail "writer never reached the mid-write kill point"
[[ "$status" != 0 ]] || fail "killed manifest writer returned success"
cmp -s "$prior_manifest" "$writer_out/required-artifacts.json" \
  || fail "killed writer replaced the prior final manifest"
if find "$writer_out" -maxdepth 1 -name '.required-artifacts.json.*' -print -quit | grep -q .; then
  fail "killed writer left staging residue"
fi

unset WRITER_BLOCK_MARKER
rm -f "$writer_out/required-artifacts.json"
writer_script="$(sugar_bx_artifact_build_script \
  first release "$writer_workspace" "$writer_out")"
case "$writer_script" in
  *'chmod 0644 "$manifest_tmp";'*'mv -f -- "$manifest_tmp" "$manifest";'*) ;;
  *) fail "manifest publication does not set host-readable mode before atomic rename" ;;
esac
WRITER_PAYLOAD_ROOT="$tmp/writer-payloads" bash -c "$writer_script"
python3 - "$writer_out" <<'PY'
import hashlib, json, pathlib, stat, sys
root = pathlib.Path(sys.argv[1])
manifest_path = root / "required-artifacts.json"
assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o644, oct(
    stat.S_IMODE(manifest_path.stat().st_mode)
)
manifest = json.loads(manifest_path.read_text())
assert len(manifest["artifacts"]) == 1, manifest
item = manifest["artifacts"][0]
assert item["name"] == "first", item
assert item["sha256"] == hashlib.sha256((root / "first").read_bytes()).hexdigest(), item
assert not list(root.glob(".required-artifacts.json.*"))
PY

# Malformed prior manifests are evidence. Quarantine them by content before the
# full artifact reset, collapse repeats, and make bounded eviction loud.
quarantine_artifacts="$tmp/quarantine-artifacts"
quarantine="$tmp/quarantine"
mkdir -p "$quarantine_artifacts" "$quarantine"
printf '{"artifacts":[' >"$quarantine_artifacts/required-artifacts.json"
corrupt_digest="$(python3 - "$quarantine_artifacts/required-artifacts.json" <<'PY'
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
sugar_bx_quarantine_required_artifacts \
  "$quarantine_artifacts" "$quarantine" 64 2>"$tmp/quarantine.err"
quarantined="$quarantine/required-artifacts.sha256-$corrupt_digest.json"
cmp -s "$quarantine_artifacts/required-artifacts.json" "$quarantined" \
  || fail "quarantine did not preserve malformed bytes"
sugar_bx_quarantine_required_artifacts \
  "$quarantine_artifacts" "$quarantine" 64 2>>"$tmp/quarantine.err"
[[ "$(find "$quarantine" -type f | wc -l | tr -d ' ')" == 1 ]] \
  || fail "identical corruption did not collapse by content"

cap_quarantine="$tmp/cap-quarantine"
mkdir -p "$cap_quarantine"
python3 - "$cap_quarantine" <<'PY'
import os, pathlib, sys
root = pathlib.Path(sys.argv[1])
for index in range(64):
    path = root / f"required-artifacts.sha256-{index:064x}.json"
    path.write_text(f"old-{index}\n")
    stamp = 1_700_000_000 + index
    os.utime(path, (stamp, stamp))
PY
sugar_bx_quarantine_required_artifacts \
  "$quarantine_artifacts" "$cap_quarantine" 64 2>"$tmp/quarantine-cap.err"
[[ "$(find "$cap_quarantine" -type f | wc -l | tr -d ' ')" == 64 ]] \
  || fail "quarantine cap did not conserve 64 entries"
[[ ! -e "$cap_quarantine/required-artifacts.sha256-$(printf '%064x' 0).json" ]] \
  || fail "quarantine did not evict the oldest entry first"
[[ -e "$cap_quarantine/required-artifacts.sha256-$corrupt_digest.json" ]] \
  || fail "quarantine evicted the newly observed corruption"
grep -Fq 'crime=artifact-manifest-quarantine-cap-exceeded' \
  "$tmp/quarantine-cap.err" || fail "quarantine eviction was silent"
grep -Fq 'currentCount=65' "$tmp/quarantine-cap.err" \
  || fail "quarantine eviction did not report its current count"

valid_artifacts="$tmp/valid-artifacts"
valid_quarantine="$tmp/valid-quarantine"
mkdir -p "$valid_artifacts" "$valid_quarantine"
printf '{"artifacts":[]}\n' >"$valid_artifacts/required-artifacts.json"
sugar_bx_quarantine_required_artifacts \
  "$valid_artifacts" "$valid_quarantine" 64
[[ "$(find "$valid_quarantine" -type f | wc -l | tr -d ' ')" == 0 ]] \
  || fail "valid manifest was quarantined"

python3 - "$repo/bin/lib/sugar-bx.sh" <<'PY'
import pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text()
body = source.split("sugar_bx_build_artifacts_docker() {", 1)[1]
body = body.split("\n}", 1)[0]
quarantine = body.index(
    'sugar_bx_quarantine_required_artifacts '
    '$(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts")'
)
reset = body.index('rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts")')
assert quarantine < reset, "malformed-manifest evidence is destroyed before quarantine"
PY

echo "PASS: sugarbin Docker execution contract"

"$repo/tests/sugarbin_managed_preconditions.sh" "$repo"
