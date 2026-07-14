# Sugarbin Execution Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `bin/sugarbin` the single artifact and execution front door for local ambient commands, native battleaxe commands, and capability-pinned Docker commands on battleaxe, while keeping Rust binaries as the only cached execution result.

**Architecture:** Preserve `sugarbin`'s current no-subcommand artifact resolver and add `run`, `cargo`, `build`, and `explain` subcommands. Move the duplicated remote synchronization machinery from `bcargo` and `brun` into a shared bx host backend, then reduce both wrappers to compatibility adapters. Managed bx execution selects immutable Docker capability closures from `sugar-build.toml`; stamped Rust executables remain separate shelf artifacts injected into every command that declares them.

**Tech Stack:** Bash 3.2-compatible scripts, Python 3.12 `tomllib`, Docker/BuildKit on battleaxe, GitHub release assets, BLAKE3-512 source stamps, SHA-256 artifact verification, Rust integration tests, fake SSH/rsync/docker shell harnesses.

## Global Constraints

- Cache Rust executable artifacts only. Never cache or reuse test execution, test output, or test verdicts.
- `--host` defaults to `local`; `--env` defaults to `ambient`.
- Local ambient execution never provisions dependencies and never invokes SSH or Docker.
- Host `bx` supports both `ambient` execution and managed Docker execution.
- Managed Docker core pins Rust/Cargo 1.96.0, Python 3.12.13, Black 26.5.1, Pyright 1.1.411, and b3sum 1.8.1.
- The native platform is derived from the selected execution route. An explicit platform is a constraint, not permission to cross-compile or select another host.
- Intel macOS builds `darwin-x86_64`; Apple Silicon macOS builds `darwin-arm64`; bx builds `linux-x86_64`.
- Preserve current `bin/sugarbin` resolver CLI and environment variables during migration.
- Preserve checkout-relative working directories, per-worktree remote roots, sync exclusions, tracked-file manifests, stale-root reaping, sync-back, foreign-binary protection, streamed output, and exact exit status.
- Required binaries are resolved before command execution. Cache hits may skip compilation but must never skip the command.
- Every executable receives an individual manifest and checksum. Building one executable cannot validate a stale sibling.
- Unsupported host/environment/platform combinations fail before command execution.

---

## File Structure

- `bin/sugarbin`: public CLI, legacy resolver dispatch, subcommand parsing, artifact resolution orchestration.
- `bin/lib/sugar-exec.sh`: host/environment/platform model, local execution, common argument and exit-code handling.
- `bin/lib/sugar-bx.sh`: shared checkout sync, remote-root lifecycle, bx ambient execution, Docker invocation, sync-back.
- `bin/bcargo`: compatibility adapter to `sugarbin cargo --host bx --env ambient`.
- `bin/brun`: compatibility adapter to `sugarbin run --host bx --env ambient`.
- `sugar-build.toml`: checked-in tool versions, capability closures, immutable image references, named task requirements.
- `tools/sugar-build/contract.py`: strict TOML reader and deterministic capability/task resolver.
- `tools/sugar-build/Dockerfile`: core and additive capability stages.
- `tools/sugar-build/entrypoint.sh`: managed-container version and stamped-artifact checks before command execution.
- `tests/sugarbin_local_exec.sh`: local ambient and platform-constraint harness.
- `tests/sugarbin_bx_exec.sh`: fake SSH/rsync harness for shared bx behavior.
- `tests/sugarbin_artifact_manifest.sh`: per-executable identity and cache-hit/miss harness.
- `tests/sugarbin_docker_exec.sh`: fake Docker/SSH harness for image selection, injection, and command execution.
- `tests/sugarbin_wrapper_compat.sh`: `bcargo` and `brun` argument-translation receipts.
- `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`: runs the shell contract suite from Cargo.
- `implementations/rust/sugar-cli/tests/bcargo_sync_contract.rs`: reads synchronization policy from `bin/lib/sugar-bx.sh` after ownership moves.

---

### Task 1: Add Subcommand Dispatch and Local Ambient Execution

**Files:**
- Create: `bin/lib/sugar-exec.sh`
- Create: `tests/sugarbin_local_exec.sh`
- Create: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`
- Modify: `bin/sugarbin`

**Interfaces:**
- Consumes: existing no-subcommand `bin/sugarbin [--bin NAME] [--profile PROFILE]` behavior.
- Produces: `sugar_exec_platform_key`, `sugar_exec_validate_route`, and `sugar_exec_local_run`; public `sugarbin run`, `cargo`, and `explain` parsing for `host=local, env=ambient`.

- [ ] **Step 1: Write the failing local execution harness**

Create `tests/sugarbin_local_exec.sh` with a temporary fake command that logs its arguments, working directory, and invocation count. Assert:

```bash
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

! grep -q . "$tmp/ssh.log"
! grep -q . "$tmp/docker.log"
```

Plant a conflicting route using the opposite of the detected platform and assert exit `2`, no command invocation, and a diagnostic containing `unsupported execution route`.

- [ ] **Step 2: Register the shell harness as a Rust integration test**

Create `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`:

```rust
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli workspace root")
        .to_path_buf()
}

#[test]
fn sugarbin_local_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_local_exec.sh"))
        .arg(&root)
        .status()
        .expect("run local execution contract");
    assert!(status.success(), "local execution contract failed: {status}");
}
```

- [ ] **Step 3: Run the focused test and verify the red state**

Run:

```bash
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract \
  sugarbin_local_execution_contract -- --nocapture
```

Expected: FAIL because `bin/sugarbin` rejects `run` as an unknown argument.

- [ ] **Step 4: Implement host-independent local execution helpers**

Create `bin/lib/sugar-exec.sh` with Bash functions using arrays rather than command strings:

```bash
sugar_exec_platform_key() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  case "$arch" in amd64|x64) arch=x86_64 ;; aarch64) arch=arm64 ;; esac
  printf '%s-%s\n' "$os" "$arch"
}

sugar_exec_validate_route() {
  local host="$1" env="$2" requested="$3" observed="$4"
  [[ "$host" == local && "$env" == ambient ]] || {
    printf 'sugarbin: unsupported execution route: host=%s env=%s\n' "$host" "$env" >&2
    return 2
  }
  [[ -z "$requested" || "$requested" == "$observed" ]] || {
    printf 'sugarbin: unsupported execution route: host=%s env=%s platform=%s available=%s\n' \
      "$host" "$env" "$requested" "$observed" >&2
    return 2
  }
}

sugar_exec_local_run() {
  "$@"
}
```

- [ ] **Step 5: Add compatibility-preserving subcommand dispatch**

At the start of `bin/sugarbin`, detect only the exact subcommands `run`, `cargo`, `build`, and `explain`. When none is present, enter the existing resolver parser unchanged. For `run`, parse `--host`, `--env`, `--platform`, `--needs`, and the `--` boundary, validate `local + ambient`, and call `sugar_exec_local_run`. For `cargo`, prepend `cargo` to the child argument array. For `explain`, print stable `key=value` rows and do not execute.

Keep `build` parsed but return the explicit diagnostic `sugarbin: build subcommand requires artifact-manifest implementation` until Task 4 owns it; do not silently route it through the legacy resolver.

- [ ] **Step 6: Run local and legacy resolver receipts**

Run the focused Rust test from Step 3 and:

```bash
bin/sugarbin --print-source-stamp | grep -E '^blake3-512:[0-9a-f]{128}$'
bin/sugarbin --help | grep -F 'Resolve a Sugar workspace binary by source stamp'
```

Expected: all PASS; the planted command count remains exactly one.

- [ ] **Step 7: Commit**

```bash
git add bin/sugarbin bin/lib/sugar-exec.sh tests/sugarbin_local_exec.sh \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs
git commit -m "Add sugarbin local execution broker"
```

---

### Task 2: Move Battleaxe Synchronization Behind the bx Host Backend

**Files:**
- Create: `bin/lib/sugar-bx.sh`
- Create: `tests/sugarbin_bx_exec.sh`
- Modify: `bin/sugarbin`
- Modify: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`
- Modify: `implementations/rust/sugar-cli/tests/bcargo_sync_contract.rs`
- Modify: `tests/bcargo_remote_root_cleanup.sh`
- Modify: `tests/brun_remote_exec.sh`

**Interfaces:**
- Consumes: `sugar_exec_validate_route`; current sync policy and fake SSH/rsync harnesses from `bcargo` and `brun`.
- Produces: `sugar_bx_sync_workspace`, `sugar_bx_run_ambient`, `sugar_bx_sync_back`, and `sugar_bx_cleanup`; `sugarbin run --host bx --env ambient`.

- [ ] **Step 1: Write the failing bx host harness**

Create `tests/sugarbin_bx_exec.sh` by reusing the fake SSH and rsync executable pattern from `tests/brun_remote_exec.sh`. Assert that:

```bash
BCARGO_SSH="$fake_ssh" BCARGO_RSYNC="$fake_rsync" \
BCARGO_REMOTE_ROOT=/home/tsavo/remote/sugar-bcargo-broker-test \
  "$repo/bin/sugarbin" run --host bx --env ambient -- "$repo/tools/check.sh" "two words"
```

performs one workspace rsync, translates `$repo/tools/check.sh` to the remote checkout, preserves the caller's repo-relative working directory, never invokes Docker, and propagates a planted remote exit `41`.

Also retain assertions for safe cleanup roots, `success` versus `always`, stale-root reaping, tracked-manifest synchronization, sync-back, and foreign ELF refusal.

- [ ] **Step 2: Register and run the bx harness red**

Add a second Rust test to `sugarbin_execution_contract.rs` that runs `tests/sugarbin_bx_exec.sh`. Run:

```bash
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract \
  sugarbin_bx_execution_contract -- --nocapture
```

Expected: FAIL with `unsupported execution route: host=bx env=ambient`.

- [ ] **Step 3: Extract the synchronization policy without changing it**

Move `exclude_args`, `sync_paths`, repo-relative path translation, remote-root derivation, stale-root reaping, tracked-manifest creation, cleanup validation, sync-back, and foreign-binary checks from `bin/brun` into `bin/lib/sugar-bx.sh`.

Expose functions with explicit arguments and no dependence on wrapper-local arrays:

```bash
sugar_bx_init REPO_ROOT LOCAL_CWD
sugar_bx_sync_workspace
sugar_bx_run_ambient COMMAND...
sugar_bx_sync_back REMOTE_ABSOLUTE LOCAL_ABSOLUTE
sugar_bx_finish STATUS
```

The backend must use `${BCARGO_REMOTE_HOST:-battleaxe}` so current callers remain compatible while `--host bx` is the public spelling.

- [ ] **Step 4: Move the sync-contract instrument to the new owner**

Update `bcargo_sync_contract.rs` so `parse_sync_rules` and `parse_sync_excludes` read `bin/lib/sugar-bx.sh`. Change diagnostics from `owner=bin/bcargo` to `owner=bin/lib/sugar-bx.sh` and replacements from `add ... to sync_paths in bin/bcargo` to the shared backend path.

Run:

```bash
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test bcargo_sync_contract -- --nocapture
```

Expected: PASS with the same artifact and class counts as before extraction.

- [ ] **Step 5: Route `sugarbin run --host bx --env ambient` through the backend**

Source `bin/lib/sugar-bx.sh` only for `host=bx`. Validate that `env=ambient`, call `sugar_bx_init`, synchronize, run the child, preserve its status, perform configured cleanup, and return the child status.

The public parser must support the existing forwarding controls:

```text
--path-prefix DIR
--env NAME[,NAME]
--sync-back REMOTE:LOCAL
--no-python-env
```

- [ ] **Step 6: Run the focused bx, local, and sync tests**

Run:

```bash
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test bcargo_sync_contract -- --nocapture
```

Expected: PASS. Local harness logs no SSH; bx harness logs SSH and no Docker.

- [ ] **Step 7: Commit**

```bash
git add bin/sugarbin bin/lib/sugar-bx.sh tests/sugarbin_bx_exec.sh \
  tests/bcargo_remote_root_cleanup.sh tests/brun_remote_exec.sh \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs \
  implementations/rust/sugar-cli/tests/bcargo_sync_contract.rs
git commit -m "Move battleaxe execution behind sugarbin"
```

---

### Task 3: Convert bcargo and brun into Compatibility Adapters

**Files:**
- Create: `tests/sugarbin_wrapper_compat.sh`
- Modify: `bin/bcargo`
- Modify: `bin/brun`
- Modify: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`
- Modify: `tests/bcargo_remote_root_cleanup.sh`
- Modify: `tests/brun_remote_exec.sh`

**Interfaces:**
- Consumes: `sugarbin cargo/run --host bx --env ambient`, bx forwarding options, and existing wrapper environment variables.
- Produces: thin `bcargo` and `brun` adapters with the same user-visible options and child exit codes.

- [ ] **Step 1: Write the wrapper translation harness**

Create a fake `bin/sugarbin` earlier on a copied fixture repo path. Make it record one NUL-delimited argument per line. Assert exact translations:

```text
bcargo --sync-bin sugar test -p sugar-cli
=> sugarbin cargo --host bx --env ambient --sync-bin sugar -- test -p sugar-cli

brun --path-prefix /x --env TOKEN -- true
=> sugarbin run --host bx --env ambient --path-prefix /x --env TOKEN -- true
```

Plant exit codes `29` and `31` in the fake broker and assert each wrapper returns the same code.

- [ ] **Step 2: Register and run the wrapper harness red**

Add `sugarbin_wrapper_compatibility_contract` to the Rust integration test and run only that test. Expected: FAIL because current wrappers execute their own SSH and rsync logic rather than delegating once.

- [ ] **Step 3: Replace `brun` with a strict adapter**

Retain its usage text and option validation, then execute:

```bash
exec "$script_dir/sugarbin" run --host bx --env ambient "$@"
```

Do not reconstruct a shell command string. Forward the original argument array.

- [ ] **Step 4: Replace `bcargo` with a strict adapter**

Retain parsing for `--sync-bin` and `--sync-bins`, then execute:

```bash
exec "$script_dir/sugarbin" cargo --host bx --env ambient \
  "${forwarded_broker_options[@]}" -- "${cargo_args[@]}"
```

Move Cargo-specific profile, target-dir, shelf prefetch, publish, and sync-bin behavior into `sugarbin cargo`; the wrapper must not inspect Cargo arguments after this task.

- [ ] **Step 5: Run all wrapper and backend receipts**

Run:

```bash
bash tests/sugarbin_wrapper_compat.sh "$PWD"
bash tests/bcargo_remote_root_cleanup.sh "$PWD"
bash tests/brun_remote_exec.sh "$PWD"
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
```

Expected: PASS. Fake logs show exactly one broker invocation per wrapper command.

- [ ] **Step 6: Commit**

```bash
git add bin/bcargo bin/brun bin/sugarbin bin/lib/sugar-bx.sh \
  tests/sugarbin_wrapper_compat.sh tests/bcargo_remote_root_cleanup.sh \
  tests/brun_remote_exec.sh \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs
git commit -m "Delegate bcargo and brun to sugarbin"
```

---

### Task 4: Replace Profile Markers with Per-Executable Build Manifests

**Files:**
- Create: `tests/sugarbin_artifact_manifest.sh`
- Modify: `bin/sugarbin`
- Modify: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`

**Interfaces:**
- Consumes: current source stamp, shelf naming, SHA-256 helper, package-to-binary mapping.
- Produces: `build_identity`, `artifact_manifest_path`, `write_artifact_manifest`, and `verify_artifact_manifest`; functional `sugarbin build`; `--needs` artifact injection for local and bx routes.

- [ ] **Step 1: Write the stale-sibling red fixture**

In `tests/sugarbin_artifact_manifest.sh`, create a fake Cargo executable that writes only the requested binary. Plant stale executable `sugar-ir-smt-lib`, run a `sugar` build, then request `sugar-ir-smt-lib`. Assert Cargo runs a second time instead of accepting the stale sibling under a shared profile marker.

Also mutate a cached executable after writing its manifest and assert the next resolution rejects it with `artifact checksum mismatch` before execution.

- [ ] **Step 2: Run the artifact harness red**

Register the shell harness and run its Rust test. Expected: FAIL because `.sugarbin-source-stamp` validates the entire profile directory and cached shelf files are trusted by filename alone.

- [ ] **Step 3: Define complete build identity**

Compute a canonical BLAKE3-512 build identity over labeled fields:

```text
sourceStamp
rustcVersionVerbose
cargoVersionVerbose
platform
targetTriple
profile
sortedFeatures
package
binary
```

Use the same length-prefixed field encoding already used by `rust_tree_stream`; do not concatenate ambiguous delimiter-separated strings.

- [ ] **Step 4: Write and verify one manifest per executable**

Store each local manifest beside its cached artifact using the shell expression
`"${binary}.sugarbin.json"`. Required JSON fields are:

```json
{
  "schema": 1,
  "binary": "sugar",
  "package": "sugar-cli",
  "sourceStamp": "blake3-512:...",
  "buildIdentity": "blake3-512:...",
  "platform": "linux-x86_64",
  "targetTriple": "x86_64-unknown-linux-gnu",
  "profile": "release",
  "features": [],
  "rustc": "rustc 1.96.0 ...",
  "cargo": "cargo 1.96.0 ...",
  "sha256": "...",
  "built": true,
  "executed": false
}
```

Resolution must verify identity fields, file presence, executable bit, and checksum. Delete the profile-wide marker after all callers use per-executable manifests.

- [ ] **Step 5: Make `build` and `--needs` use artifact resolution**

`sugarbin build` resolves or builds every comma-separated binary in `--needs`, defaulting to `sugar`. `run --needs` resolves binaries before executing and exports stable variables:

```text
SUGAR_BIN=/home/tsavo/.cache/sugar/binaries/sugar-linux-x86_64-release-blake3-512_abc/sugar
SUGAR_BINARY_DIR=/home/tsavo/.cache/sugar/binaries/sugar-linux-x86_64-release-blake3-512_abc
PATH=/home/tsavo/.cache/sugar/binaries/sugar-linux-x86_64-release-blake3-512_abc:$PATH
```

On bx, resolve the Linux artifact on bx and place it under the remote target root. Never sync an ELF into the Mac target directory.

- [ ] **Step 6: Run cache hit, miss, corruption, and command-count receipts**

Run:

```bash
bash tests/sugarbin_artifact_manifest.sh "$PWD"
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
```

Expected: PASS. A shelf hit records zero Cargo invocations and one child command invocation; a miss records one Cargo invocation and one child invocation.

- [ ] **Step 7: Commit**

```bash
git add bin/sugarbin tests/sugarbin_artifact_manifest.sh \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs
git commit -m "Validate each sugar binary artifact"
```

---

### Task 5: Add the Declarative Build and Capability Contract

**Files:**
- Create: `sugar-build.toml`
- Create: `tools/sugar-build/contract.py`
- Create: `tests/test_sugar_build_contract.py`
- Modify: `bin/sugarbin`

**Interfaces:**
- Consumes: host/environment parser and `--needs` binary names.
- Produces: `contract.py resolve-environment`, `resolve-task`, and `tool-versions` JSON commands; named tasks and deterministic capability closures.

- [ ] **Step 1: Write strict parser tests**

Create tests derived from the real checked-in TOML shape. Pin:

```python
def test_core_versions_are_exact():
    result = resolve_environment("docker:core")
    assert result["tools"] == {
        "rust": "1.96.0",
        "cargo": "1.96.0",
        "python": "3.12.13",
        "black": "26.5.1",
        "pyright": "1.1.411",
        "b3sum": "1.8.1",
    }

def test_capability_order_does_not_change_digest_input():
    assert resolve_environment("docker:z3,python-scientific") == \
           resolve_environment("docker:python-scientific,z3")

def test_unknown_capability_is_loud():
    with pytest.raises(ContractError, match="unknown capability"):
        resolve_environment("docker:not-real")
```

Also test duplicate definitions, dependency cycles, missing immutable image references, unknown task binaries, and empty command arrays.

- [ ] **Step 2: Run the parser tests red**

Run:

```bash
python3.12 -m pytest tests/test_sugar_build_contract.py -q
```

Expected: collection FAIL because `tools/sugar-build/contract.py` does not exist.

- [ ] **Step 3: Create the checked-in contract**

Define exact core versions and capability dependencies in `sugar-build.toml`:

```toml
schema = 1

[tools]
rust = "1.96.0"
cargo = "1.96.0"
python = "3.12.13"
black = "26.5.1"
pyright = "1.1.411"
b3sum = "1.8.1"

[capabilities.core]
depends = []

[capabilities.solver-z3]
depends = ["core"]

[capabilities.solver-coq]
depends = ["core"]

[capabilities.python-scientific]
depends = ["core"]

[tasks.python-unit]
capabilities = ["core"]
binaries = []
command = ["python", "-m", "pytest"]

[tasks.examples-gate]
capabilities = ["python-scientific", "solver-z3", "solver-coq", "java", "node", "vampire"]
binaries = ["sugar", "sugar-ir-smt-lib"]
command = ["make", "examples-gate"]
```

Image digests are added only in Task 6 after the corresponding image exists; until then Docker resolution must fail with `capability closure has no built image`, while ambient routes remain usable.

- [ ] **Step 4: Implement deterministic TOML resolution**

Use Python 3.12 `tomllib`. Resolve dependency closure with a visiting/visited depth-first traversal, reject cycles, sort the final capability set, and emit canonical JSON with `sort_keys=True` and compact separators. Never import third-party TOML libraries.

CLI examples:

```bash
python3.12 tools/sugar-build/contract.py tool-versions
python3.12 tools/sugar-build/contract.py resolve-environment docker:solver-z3
python3.12 tools/sugar-build/contract.py resolve-task examples-gate
```

- [ ] **Step 5: Integrate named tasks and explain output**

Add `--task NAME` to `sugarbin run`. Merge task command arguments with arguments after `--`, append rather than replace task defaults, and reject simultaneous contradictory `--needs` declarations. `explain` prints the sorted capability closure and task binaries from the parser output.

- [ ] **Step 6: Run focused parser and explain receipts**

Run:

```bash
python3.12 -m pytest tests/test_sugar_build_contract.py -q
bin/sugarbin explain --host bx --env docker:solver-z3 --needs sugar
bin/sugarbin explain --host bx --task examples-gate
```

Expected: tests PASS; explain output is deterministic across repeated runs.

- [ ] **Step 7: Commit**

```bash
git add sugar-build.toml tools/sugar-build/contract.py \
  tests/test_sugar_build_contract.py bin/sugarbin
git commit -m "Declare sugar build capabilities"
```

---

### Task 6: Build and Verify the Managed Docker Core

**Files:**
- Create: `tools/sugar-build/Dockerfile`
- Create: `tools/sugar-build/entrypoint.sh`
- Create: `tests/sugarbin_docker_exec.sh`
- Modify: `sugar-build.toml`
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `bin/sugarbin`
- Modify: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`

**Interfaces:**
- Consumes: deterministic capability closure, bx synchronization, artifact injection, core version pins.
- Produces: immutable `core` image on bx; `sugar_bx_run_docker IMAGE_DIGEST COMMAND...`; `sugarbin run --host bx --env docker:...`.

- [ ] **Step 1: Write the fake Docker selection and execution harness**

Use fake SSH and Docker commands to assert:

- `docker:core` selects one exact `@sha256:` image reference.
- `docker:solver-z3` selects its own exact closure image.
- repo checkout mounts at `/workspace/sugar`.
- caller's relative working directory `implementations/python` becomes
  `/workspace/sugar/implementations/python`.
- required artifacts mount read-only at `/opt/sugar/bin`.
- `SUGAR_BIN=/opt/sugar/bin/sugar` and `PATH` starts with `/opt/sugar/bin`.
- the child command executes exactly once on both artifact hit and miss.
- a planted child exit `43` returns `43`.
- local and bx ambient routes never invoke Docker.

- [ ] **Step 2: Run the Docker harness red**

Register it in the Rust integration test and run only that test. Expected: FAIL with `unsupported execution route: host=bx env=docker:core`.

- [ ] **Step 3: Create the core Docker stage**

Use `python:3.12.13-slim-bookworm` as the base tag while developing. Resolve its multi-arch digest on bx before commit:

```bash
docker buildx imagetools inspect python:3.12.13-slim-bookworm \
  --format '{{json .Manifest}}' | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["digest"])'
```

Before committing, replace the tag-only `FROM` line with
`python:3.12.13-slim-bookworm@${digest}`, where `digest` is the exact output of
the preceding command. The committed Dockerfile test rejects any `FROM` line
without `@sha256:`.

The core stage installs Rust/Cargo 1.96.0 through rustup, then:

```dockerfile
RUN python -m pip install --no-cache-dir \
      black==26.5.1 pyright==1.1.411 \
 && cargo install --locked b3sum --version 1.8.1
```

Copy `entrypoint.sh` and make it the image entrypoint.

- [ ] **Step 4: Make the entrypoint verify the managed contract**

Before `exec "$@"`, compare exact normalized outputs from:

```text
rustc --version
cargo --version
python --version
black --version
python -m pyright --version
b3sum --version
```

When `/opt/sugar/required-artifacts.json` exists, verify every named file and SHA-256 before exporting `SUGAR_BIN`. A mismatch exits `70` with `managed environment contract mismatch` or `artifact checksum mismatch`.

- [ ] **Step 5: Build core on bx and record the immutable image digest**

Run through the ambient bx backend:

```bash
bin/sugarbin run --host bx --env ambient -- \
  docker buildx build --load \
  --target core \
  --tag ghcr.io/tsavo/sugar-env:core-2026-07-14 \
  -f tools/sugar-build/Dockerfile .

bin/sugarbin run --host bx --env ambient -- \
  docker image inspect ghcr.io/tsavo/sugar-env:core-2026-07-14 \
  --format '{{index .RepoDigests 0}}'
```

Push the image, record the exact returned digest in `sugar-build.toml`, then pull and run by digest to print all six versions.

- [ ] **Step 6: Implement bx Docker execution**

In `sugar_bx_run_docker`, construct a Docker argument array that includes:

```text
--rm
--workdir /workspace/sugar/implementations/python
--mount type=bind,src=/home/tsavo/remote/sugar-bcargo-example/sugar,dst=/workspace/sugar
--mount type=bind,src=/home/tsavo/remote/sugar-bcargo-example/artifacts,dst=/opt/sugar/bin,readonly
--mount type=bind,src=/home/tsavo/remote/sugar-bcargo-example/required-artifacts.json,dst=/opt/sugar/required-artifacts.json,readonly
```

Pass only explicitly forwarded environment variables. Never mount the Docker socket into task containers.

- [ ] **Step 7: Run focused fake and real core receipts**

Run:

```bash
bash tests/sugarbin_docker_exec.sh "$PWD"
bin/sugarbin run --host bx --env docker:core -- \
  sh -lc 'rustc --version; cargo --version; python --version; black --version; python -m pyright --version; b3sum --version'
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
```

Expected: exact pinned versions, all tests PASS, no command-result reuse.

- [ ] **Step 8: Commit**

```bash
git add tools/sugar-build/Dockerfile tools/sugar-build/entrypoint.sh \
  tests/sugarbin_docker_exec.sh sugar-build.toml bin/sugarbin \
  bin/lib/sugar-bx.sh \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs
git commit -m "Add managed battleaxe Docker core"
```

---

### Task 7: Add Capability Images and Migrate Named Tasks

**Files:**
- Modify: `tools/sugar-build/Dockerfile`
- Modify: `sugar-build.toml`
- Modify: `tests/test_sugar_build_contract.py`
- Modify: `tests/sugarbin_docker_exec.sh`
- Modify: `Makefile`
- Modify: `bin/bpytest`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: managed core, deterministic capability resolver, named tasks, stamped artifact injection.
- Produces: immutable closure images for Z3, Coq, scientific Python, Java/Maven, Node/pnpm, Vampire, and the initial named test tasks.

- [ ] **Step 1: Add one red version or executable pin per capability**

Extend parser tests so every capability has an exact version declaration and immutable closure image. Extend the Docker harness to request each named task and assert its resolved digest and required binaries.

Add entrypoint smoke commands to the task contract:

```text
z3 --version
coqc --version
python -c 'import numpy, pandas'
java -version and mvn -version
node --version and pnpm --version
vampire --version
```

- [ ] **Step 2: Run capability tests red**

Run:

```bash
python3.12 -m pytest tests/test_sugar_build_contract.py -q
bash tests/sugarbin_docker_exec.sh "$PWD"
```

Expected: FAIL because capability image references are absent.

- [ ] **Step 3: Add additive Docker stages**

Each stage starts from `core` or the smallest prior closure and installs only
its declared tool family. Build and push each closure on bx, then record the
immutable digest. Do not use mutable tags in runtime resolution.

The scientific Python stage installs exact NumPy and pandas versions from
`sugar-build.toml`. Before editing the contract, run the existing pandas and
NumPy source installers in explain/dry-run mode and copy the versions they
report. Commit the resulting concrete PEP 440 versions and add a test comparing
the Docker imports' `__version__` values to those two contract fields. If the
existing installers do not expose a single version, stop this capability task
and add that missing version owner before building the image.

- [ ] **Step 4: Define initial named task closures**

At minimum, declare:

```text
python-unit
python-lift
rust-unit
examples-gate
pandas-wall
numpy-wall
restored-suite-scoreboard
```

Each task lists exact capabilities and binaries. The command always runs; no
task schema field may represent a cached verdict.

- [ ] **Step 5: Route bpytest and selected Make targets through named tasks**

Change `bin/bpytest` to delegate environment and host execution to:

```bash
bin/sugarbin run --host bx --task python-unit -- "$@"
```

Keep its existing user-facing options by translating them into broker options.
Update only Make or workflow call sites that already target battleaxe. Local
developer targets remain ambient.

- [ ] **Step 6: Run focused named-task receipts**

Run one seconds-fast command per closure, plus:

```bash
bin/sugarbin explain --host bx --task python-unit
bin/sugarbin explain --host bx --task examples-gate
bin/sugarbin run --host bx --task python-unit -- \
  tests/test_type_checker_ratchet.py -q
```

Expected: explain names immutable digests and required binaries; the selected
test actually executes and returns its current real status.

- [ ] **Step 7: Run compatibility contracts**

Run:

```bash
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test bcargo_sync_contract -- --nocapture
```

Expected: PASS for local, bx ambient, bx Docker, wrappers, artifact identity,
sync policy, and named tasks.

- [ ] **Step 8: Commit**

```bash
git add tools/sugar-build/Dockerfile sugar-build.toml \
  tests/test_sugar_build_contract.py tests/sugarbin_docker_exec.sh \
  Makefile bin/bpytest .github/workflows/ci.yml
git commit -m "Compose managed Sugar test environments"
```

---

### Task 8: Document Operations and Retire Superseded Provisioning

**Files:**
- Create: `docs/build-execution.md`
- Modify: `Makefile`
- Modify: `bin/bcargo`
- Modify: `bin/brun`
- Modify: `bin/bpytest`
- Modify: `AGENTS.md`
- Modify: `implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs`

**Interfaces:**
- Consumes: completed broker, wrappers, task contract, immutable capability images.
- Produces: operator documentation, one authoritative provisioning path, and a static retirement instrument for removed duplicate logic.

- [ ] **Step 1: Add a red duplicate-ownership instrument**

Add a Rust test that reads `bcargo`, `brun`, and `bpytest` and refuses these
implementation shapes outside `bin/lib/sugar-bx.sh`:

```text
sync_paths=(
exclude_args=(
rsync -azR
find /home/tsavo/remote ... sugar-bcargo-*
make --quiet bcargo-python-kit-env
```

Expected initial result: FAIL until the last duplicated provisioning paths are removed.

- [ ] **Step 2: Remove superseded wrapper provisioning**

Delete `bcargo-python-kit-env` ownership from wrappers and remove its Makefile
target only after all tracked callers use Docker tasks or explicitly choose bx
ambient. Keep ambient execution honest: it may fail when battleaxe lacks a
dependency; it must not silently provision one.

- [ ] **Step 3: Write operator documentation**

Document:

- local ambient versus bx ambient versus bx Docker
- exact commands for artifact resolution, run, cargo, build, and explain
- capability and task declaration rules
- how to add and publish a capability image
- artifact manifest fields and shelf layout
- cache-hit versus command-execution semantics
- unsupported route diagnostics
- remote-root cleanup and recovery
- why tests are never cached

- [ ] **Step 4: Update repository agent guidance**

Add concise routing guidance to `AGENTS.md`:

```text
Use `bin/sugarbin run --host bx --env docker:solver-z3` for managed remote
execution. `bcargo`, `brun`, and `bpytest` are compatibility adapters. A binary
cache hit may skip compilation, never command or test execution.
```

- [ ] **Step 5: Run the complete focused contract surface**

Run:

```bash
python3.12 -m pytest tests/test_sugar_build_contract.py -q
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test bcargo_sync_contract -- --nocapture
```

Expected: all PASS. No full suite or wall is required for this implementation plan; merged-main telemetry measures broader effects.

- [ ] **Step 6: Commit**

```bash
git add docs/build-execution.md AGENTS.md Makefile bin/bcargo bin/brun bin/bpytest \
  implementations/rust/sugar-cli/tests/sugarbin_execution_contract.rs
git commit -m "Document unified Sugar build execution"
```
