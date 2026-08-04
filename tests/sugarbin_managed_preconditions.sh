#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_managed_preconditions.sh REPO_ROOT}"
contract="$repo/tools/sugar-build/contract.py"
preflight="$repo/tools/sugar-build/preflight.py"
axes="$repo/tests/fixtures/managed_entrance_axes.json"

fail() { echo "FAIL: $*" >&2; exit 1; }

tmp="$(mktemp -d "${TMPDIR:-/tmp}/managed-preconditions.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

plan="$(python3 "$contract" resolve-preconditions showcases \
  --host bx --repo-root "$repo")"

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
