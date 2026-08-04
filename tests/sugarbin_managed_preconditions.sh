#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_managed_preconditions.sh REPO_ROOT}"
contract="$repo/tools/sugar-build/contract.py"
preflight="$repo/tools/sugar-build/preflight.py"
axes="$repo/tests/fixtures/managed_entrance_axes.json"

fail() { echo "FAIL: $*" >&2; exit 1; }

tmp="$(mktemp -d "${TMPDIR:-/tmp}/managed-preconditions.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

task_environment="$(python3 "$contract" resolve-task-environment showcases)"
python3 - "$task_environment" <<'PY'
import json
import sys

environment = json.loads(sys.argv[1])
assert environment["image"] == (
    "ghcr.io/tsavo/sugar-env@sha256:"
    "c8f9964d2a9d57fd36433d2e3bfe5d6a9c5a4367ff76e8aa5e3f53c0c28a2e2f"
), environment
assert environment["preflight"] == "managed-entrypoint/v1", environment
PY

python3 - "$repo" "$tmp/task-image-fixtures" <<'PY'
import importlib.util
import pathlib
import shutil
import sys

repo = pathlib.Path(sys.argv[1])
fixture_root = pathlib.Path(sys.argv[2])
fixture_root.mkdir()
contract_path = fixture_root / "sugar-build.toml"
shutil.copy2(repo / "sugar-build.toml", contract_path)

spec = importlib.util.spec_from_file_location(
    "task_image_contract", repo / "tools/sugar-build/contract.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

fallback = contract.resolve_task_environment("examples-gate", contract_path)
assert fallback["preflight"] == "workspace-wrapper/v1", fallback
assert fallback["image"] != contract.resolve_task_environment(
    "showcases", contract_path
)["image"], fallback

original = contract_path.read_text()
task_image_digest = (
    "c8f9964d2a9d57fd36433d2e3bfe5d6a9c5a4367ff76e8aa5e3f53c0c28a2e2f"
)
contract_path.write_text(
    original.replace("@sha256:" + task_image_digest, ":latest")
)
try:
    contract.resolve_task_environment("showcases", contract_path)
except contract.ContractError as error:
    assert "immutable" in str(error), error
else:
    raise AssertionError("mutable task image reference did not refuse")

contract_path.write_text(
    original.replace("managed-entrypoint/v1", "unknown-entrypoint/v9")
)
try:
    contract.resolve_task_environment("showcases", contract_path)
except contract.ContractError as error:
    assert "preflight protocol" in str(error), error
else:
    raise AssertionError("unknown task image preflight did not refuse")
PY

plan="$(python3 "$contract" resolve-preconditions showcases \
  --host bx --repo-root "$repo")"

status=0
python3 "$contract" resolve-task-image-build showcases \
  --repo-root "$repo" >"$tmp/image-build.json" \
  2>"$tmp/image-build.err" || status=$?
[[ "$status" == 0 ]] || fail "task image build projection refused: $(cat "$tmp/image-build.err")"
python3 - "$tmp/image-build.json" <<'PY'
import json
import pathlib
import sys

projection = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert projection == {
    "aptPackages": ["git"],
    "rustComponents": ["rust-src"],
    "rustToolchain": "1.96.0",
    "schemaVersion": 1,
    "target": "showcases-closure",
    "task": "showcases",
}, projection
PY

python3 - "$repo" "$tmp/derived-fixture" <<'PY'
import importlib.util
import pathlib
import shutil
import sys

repo = pathlib.Path(sys.argv[1])
fixture = pathlib.Path(sys.argv[2])
fixture.mkdir()
shutil.copy2(repo / "Makefile", fixture / "Makefile")
shutil.copy2(repo / "sugar-build.toml", fixture / "sugar-build.toml")
(fixture / ".github").mkdir()
shutil.copy2(
    repo / ".github/showcase-retirements.json",
    fixture / ".github/showcase-retirements.json",
)
std_core = fixture / "examples/std-core-showcase"
std_core.mkdir(parents=True)
std_core.joinpath("rust-toolchain.toml").write_text(
    '[toolchain]\nchannel = "1.96.0"\ncomponents = ["rust-src", "rustfmt"]\nprofile = "minimal"\n'
)
contract_text = (fixture / "sugar-build.toml").read_text()
contract_text = contract_text.replace(
    'required_commands = ["git"]',
    'required_commands = ["git", "curl"]',
)
(fixture / "sugar-build.toml").write_text(contract_text)

spec = importlib.util.spec_from_file_location(
    "stage_two_contract", repo / "tools/sugar-build/contract.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
projection = contract.resolve_task_image_build(
    "showcases", fixture, fixture / "sugar-build.toml"
)
assert projection["aptPackages"] == ["curl", "git"], projection
assert projection["rustComponents"] == ["rust-src", "rustfmt"], projection

second = fixture / "examples/numpy-showcase"
second.mkdir(parents=True)
second.joinpath("rust-toolchain.toml").write_text(
    '[toolchain]\nchannel = "1.95.0"\ncomponents = ["rust-src"]\nprofile = "minimal"\n'
)
try:
    contract.resolve_task_image_build(
        "showcases", fixture, fixture / "sugar-build.toml"
    )
except contract.ContractError as error:
    assert "exactly one Rust toolchain" in str(error), error
else:
    raise AssertionError("mixed Rust toolchains did not refuse")
PY

mkdir -p "$tmp/image-build-bin"
cat >"$tmp/image-build-bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$DOCKER_BUILD_ARGS"
SH
chmod +x "$tmp/image-build-bin/docker"
DOCKER_BUILD_ARGS="$tmp/docker-build.args" \
  PATH="$tmp/image-build-bin:$PATH" \
  python3 "$repo/tools/sugar-build/build_task_image.py" showcases \
    --repo-root "$repo" --tag ghcr.io/tsavo/sugar-env:stage-two-tooth --load
python3 - "$tmp/docker-build.args" <<'PY'
import pathlib
import sys

args = pathlib.Path(sys.argv[1]).read_text().splitlines()
assert args[:2] == ["buildx", "build"], args
assert args[args.index("--platform") + 1] == "linux/amd64", args
assert args[args.index("--target") + 1] == "showcases-closure", args
build_args = [
    args[index + 1]
    for index, value in enumerate(args)
    if value == "--build-arg"
]
assert "MANAGED_APT_PACKAGES=git" in build_args, build_args
assert "MANAGED_RUST_TOOLCHAIN=1.96.0" in build_args, build_args
assert "MANAGED_RUST_COMPONENTS=rust-src" in build_args, build_args
assert "--load" in args and "--push" not in args, args
PY

python3 - "$repo/tools/sugar-build/Dockerfile" <<'PY'
import pathlib
import sys

dockerfile = pathlib.Path(sys.argv[1]).read_text()
stage = dockerfile.split("FROM examples-closure AS showcases-closure", 1)[1]
assert "ARG MANAGED_APT_PACKAGES" in stage
assert "ARG MANAGED_RUST_TOOLCHAIN" in stage
assert "ARG MANAGED_RUST_COMPONENTS" in stage
assert 'apt-get install -y --no-install-recommends ${MANAGED_APT_PACKAGES}' in stage
assert 'rustup component add --toolchain "${MANAGED_RUST_TOOLCHAIN}" "${component}"' in stage
assert "COPY tools/sugar-build/preflight.py /usr/local/lib/sugar/managed-preflight.py" in stage
assert "chmod 0555 /usr/local/lib/sugar/managed-preflight.py" in stage
PY

python3 - "$plan" "$repo" <<'PY'
import json
import pathlib
import sys

plan = json.loads(sys.argv[1])
repo = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(repo / "tools"))
import showcase_scope

roster = showcase_scope.makefile_showcase_roster(repo / "Makefile")
retirements = showcase_scope.load_manifest(
    repo / ".github/showcase-retirements.json", roster
)
assert plan["schemaVersion"] == 1, plan
assert plan["task"] == "showcases", plan
assert plan["host"] == "bx", plan
assert plan["roster"]["enrolled"] == len(roster), plan["roster"]
assert plan["roster"]["retired"] == len(retirements), plan["roster"]
assert plan["roster"]["active"] == len(roster) - len(retirements), plan["roster"]
assert plan["roster"]["active"] + plan["roster"]["retired"] == len(roster)
components = [
    check
    for check in plan["checks"]
    if check["kind"] == "toolchain-component"
]
assert any(
    check["name"] == "rust-src"
    and check["channel"] == "1.96.0"
    and check["source"] == "examples/std-core-showcase/rust-toolchain.toml"
    for check in components
), components
commands = [check for check in plan["checks"] if check["kind"] == "command"]
assert any(
    check["name"] == "git"
    and check["source"] == "task.closure.required_commands"
    for check in commands
), commands
artifacts = [
    (check["profile"], check["name"])
    for check in plan["checks"]
    if check["kind"] == "artifact-manifest"
]
assert ("release", "sugar") in artifacts, artifacts
assert ("debug", "sugar-ir-lean") in artifacts, artifacts
PY

python3 "$preflight" falsify --plan-json "$plan" --axes "$axes" \
  >"$tmp/falsify.out" 2>"$tmp/falsify.err"
grep -Fq 'R_precondition_axes_discovered=9' "$tmp/falsify.out" \
  || fail "falsifier did not enumerate all nine axes"
grep -Fq 'R_precondition_axes_predicted=9' "$tmp/falsify.out" \
  || fail "falsifier did not predict all nine axes"
grep -Fq 'R_unpredicted_precondition_axes=0' "$tmp/falsify.out" \
  || fail "falsifier did not prove zero uncovered axes"

python3 - "$axes" "$tmp/unpredicted.json" <<'PY'
import json
import pathlib
import sys

source, destination = map(pathlib.Path, sys.argv[1:])
payload = json.loads(source.read_text())
payload["axes"][0]["expectedKind"] = "not-derived"
destination.write_text(json.dumps(payload, indent=2) + "\n")
PY

status=0
python3 "$preflight" falsify --plan-json "$plan" \
  --axes "$tmp/unpredicted.json" >"$tmp/unpredicted.out" \
  2>"$tmp/unpredicted.err" || status=$?
[[ "$status" == 70 ]] || fail "unpredicted axis status=$status, want 70"
grep -Fq 'crime=unpredicted-precondition-axis' "$tmp/unpredicted.err" \
  || fail "unpredicted axis did not refuse by name"
grep -Fq 'axis=git-absent-in-managed-image' "$tmp/unpredicted.err" \
  || fail "unpredicted refusal did not name its row"
grep -Fq 'R_unpredicted_precondition_axes=1' "$tmp/unpredicted.out" \
  || fail "unpredicted receipt did not conserve the missing row"

# A registered command closure must not enter battleaxe through raw brun argv.
cat >"$tmp/ssh" <<'SH'
#!/usr/bin/env bash
: >"$TRANSPORT_MARKER"
exit 0
SH
cat >"$tmp/rsync" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$tmp/ssh" "$tmp/rsync"
export TRANSPORT_MARKER="$tmp/transport-called"
status=0
(cd "$repo" && BCARGO_REAP_DAYS=0 BCARGO_SSH="$tmp/ssh" \
  BCARGO_RSYNC="$tmp/rsync" bin/sugarbin run --host bx -- \
  make test-showcases) >"$tmp/unmanaged.out" 2>"$tmp/unmanaged.err" \
  || status=$?
[[ "$status" == 70 ]] || fail "unmanaged registered command status=$status, want 70"
grep -Fq 'crime=unmanaged-command-closure' "$tmp/unmanaged.err" \
  || fail "unmanaged registered command did not refuse by name"
grep -Fq 'task=showcases' "$tmp/unmanaged.err" \
  || fail "unmanaged registered command did not name its task"
[[ ! -e "$TRANSPORT_MARKER" ]] \
  || fail "unmanaged registered command reached transport before refusal"

rm -f "$TRANSPORT_MARKER"
(cd "$repo" && BCARGO_REAP_DAYS=0 BCARGO_SSH="$tmp/ssh" \
  BCARGO_RSYNC="$tmp/rsync" bin/sugarbin run --host bx -- true) \
  >"$tmp/adhoc.out" 2>"$tmp/adhoc.err"
[[ -e "$TRANSPORT_MARKER" ]] \
  || fail "unclaimed ad-hoc command was refused before transport"

# Missing declarations refuse before the subject, with their producing source.
python3 - "$plan" "$tmp/missing-command.json" <<'PY'
import json
import pathlib
import sys

plan = json.loads(sys.argv[1])
for check in plan["checks"]:
    if check["kind"] == "command":
        check["name"] = "sugar-command-definitely-absent"
pathlib.Path(sys.argv[2]).write_text(json.dumps(plan))
PY
status=0
PATH="$tmp:$PATH" python3 "$preflight" run \
  --plan-json "$(cat "$tmp/missing-command.json")" \
  --artifact-root "$tmp/artifacts" -- sh -c \
  ": >'$tmp/missing-command-subject'" >"$tmp/missing-command.out" \
  2>"$tmp/missing-command.err" || status=$?
[[ "$status" == 70 ]] || fail "missing command status=$status, want 70"
grep -Fq 'crime=missing-managed-command' "$tmp/missing-command.err" \
  || fail "missing command did not refuse by name"
grep -Fq 'name=sugar-command-definitely-absent' "$tmp/missing-command.err" \
  || fail "missing command refusal did not name command"
[[ ! -e "$tmp/missing-command-subject" ]] \
  || fail "missing command executed subject"

mkdir -p "$tmp/toolchain-bin"
cat >"$tmp/toolchain-bin/rustup" <<'SH'
#!/usr/bin/env bash
printf 'rustfmt-x86_64-unknown-linux-gnu (installed)\n'
SH
chmod +x "$tmp/toolchain-bin/rustup"
python3 - "$plan" "$tmp/missing-component.json" <<'PY'
import json
import pathlib
import sys

plan = json.loads(sys.argv[1])
plan["checks"] = [
    check
    for check in plan["checks"]
    if check["kind"] in {"command", "toolchain-component"}
]
for check in plan["checks"]:
    if check["kind"] == "command":
        check["name"] = "sh"
pathlib.Path(sys.argv[2]).write_text(json.dumps(plan))
PY
status=0
PATH="$tmp/toolchain-bin:/usr/bin:/bin" python3 "$preflight" run \
  --plan-json "$(cat "$tmp/missing-component.json")" \
  --artifact-root "$tmp/artifacts" -- sh -c \
  ": >'$tmp/missing-component-subject'" >"$tmp/missing-component.out" \
  2>"$tmp/missing-component.err" || status=$?
[[ "$status" == 70 ]] || fail "missing component status=$status, want 70"
grep -Fq 'crime=missing-toolchain-component' "$tmp/missing-component.err" \
  || fail "missing toolchain component did not refuse by name"
grep -Fq 'name=rust-src' "$tmp/missing-component.err" \
  || fail "missing toolchain refusal did not name rust-src"
grep -Fq 'channel=1.96.0' "$tmp/missing-component.err" \
  || fail "missing toolchain refusal did not name channel"
[[ ! -e "$tmp/missing-component-subject" ]] \
  || fail "missing toolchain component executed subject"

echo 'PASS: managed entrance precondition derivation and nine-axis falsification'
