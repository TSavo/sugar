# Managed Entrance Precondition Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land stage one of the managed showcase entrance: a declared command closure, executable nine-axis authority falsification, early named refusal, finite rebuild-lock failure, and artifact ABI authentication.

**Architecture:** `sugar-build.toml` owns the named showcase task and the roots from which its active scripts, toolchain components, commands, and profile-qualified artifacts are derived. `contract.py` produces a canonical plan; `preflight.py` authenticates it before the task subject; existing sugarbin shell-tier contracts enroll the teeth. Stage one publishes no image, so the current image must honestly refuse missing `git` and `rust-src` until stage two supplies a satisfying digest.

**Tech Stack:** Python 3.12 standard library, Bash, TOML, JSON, existing sugarbin/battleaxe transport.

## Global Constraints

- Derive obligations from task, roster, retirement, toolchain, artifact, and route authority; never encode the nine incidents as production policy.
- An axis without a producing declaration or route fact is unmeasured and refuses `crime=unpredicted-precondition-axis`.
- Rebuild-lock failures terminate; no `holder_pid=unknown heartbeat_age=999999` retry loop is allowed.
- Detached remote execution remains unsolved and receives no managed success claim.
- Stage one must not modify `tools/sugar-build/Dockerfile` or any image digest.
- Preserve the closing-account JSON SHA-256 `20c96121eb1fe9715a5aa63dd74218eaefd15f5b52c6295378c91514fa5afaf1`.

---

### Task 1: Declare and derive the managed showcase closure

**Files:**
- Modify: `sugar-build.toml`
- Modify: `tools/sugar-build/contract.py`
- Create: `tools/sugar-build/preflight.py`
- Create: `tests/fixtures/managed_entrance_axes.json`
- Create: `tests/sugarbin_managed_preconditions.sh`
- Modify: `tests/sugarbin_docker_exec.sh`

**Interfaces:**
- Produces: `resolve_task_preconditions(name, host, repo_root, path=DEFAULT_CONTRACT) -> dict`.
- Produces: CLI `contract.py resolve-preconditions TASK --host bx --repo-root PATH`.
- Produces: CLI `contract.py match-command -- ARGV...`.
- Produces: CLI `preflight.py falsify --plan-json JSON --axes PATH`.

- [ ] **Step 1: Write the failing derivation contract**

Create the nine-row JSON fixture. Each row contains `axis`, `expectedKind`, and `expectedSourcePrefix`. Add a shell contract that resolves the showcase plan and runs the falsifier:

```bash
plan="$(python3 "$repo/tools/sugar-build/contract.py" \
  resolve-preconditions showcases --host bx --repo-root "$repo")"
python3 "$repo/tools/sugar-build/preflight.py" falsify \
  --plan-json "$plan" \
  --axes "$repo/tests/fixtures/managed_entrance_axes.json"
```

Assert the plan counts equal the live roster and retirement authorities, `rust-src` is sourced from `examples/std-core-showcase/rust-toolchain.toml`, `git` is sourced from task closure, profile-qualified artifacts and route facts are present, and `R_unpredicted_precondition_axes=0`. Change one copied fixture row to `expectedKind=not-derived`; require exit 70 and `crime=unpredicted-precondition-axis`.

- [ ] **Step 2: Run RED**

```bash
bash tests/sugarbin_managed_preconditions.sh "$PWD"
```

Expected: nonzero because the task, resolver, and falsifier do not exist.

- [ ] **Step 3: Implement the strict closure**

Add the approved `[tasks.showcases]` and nested closure. Extend `resolve_task` to accept the optional closure and reject unknown keys, invalid profiles, duplicate artifacts, absent roster paths, retirements outside the roster, missing adjacent manifests, and malformed toolchain tables.

Build checks only from declarations and route facts:

```python
checks = [
    *command_checks(closure["required_commands"], "task.closure.required_commands"),
    *toolchain_component_checks(active_scripts, closure["adjacent_manifests"]),
    *artifact_checks(closure["artifacts"]),
    *route_checks(host),
]
```

`route_checks("bx")` emits the closed kinds `cache-access`, `shelf-access`, `rebuild-lock`, `process-lifetime`, and `declared-interpreter`; no incident label appears in production code.

- [ ] **Step 4: Implement executable falsification**

For every fixture row require one plan check with matching `kind` and source prefix. Print uncovered rows and exact discovered/predicted/unpredicted counts. Return 70 if any row is uncovered.

- [ ] **Step 5: Enroll and verify GREEN**

Invoke the new shell contract from `tests/sugarbin_docker_exec.sh`, preserving the nine-test shell-tier roster. Run both contracts plus `git diff --check`. Commit:

```bash
git add sugar-build.toml tools/sugar-build/contract.py tools/sugar-build/preflight.py \
  tests/fixtures/managed_entrance_axes.json tests/sugarbin_managed_preconditions.sh \
  tests/sugarbin_docker_exec.sh
git commit -m "Instrument managed showcase entrance authority"
```

### Task 2: Refuse unmanaged command closure and check declared prerequisites

**Files:**
- Modify: `bin/sugarbin`
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `tools/sugar-build/preflight.py`
- Modify: `tests/sugarbin_managed_preconditions.sh`
- Modify: `tests/sugarbin_docker_exec.sh`

**Interfaces:**
- Produces: `preflight.py run --plan-json JSON --artifact-root PATH -- COMMAND...`.
- Produces: transport-owned `SUGAR_BX_MANAGED_PRECONDITION_PLAN`.

- [ ] **Step 1: Add RED twins**

Prove raw `bin/sugarbin run --host bx -- make test-showcases` refuses before SSH/Docker with exit 70, `crime=unmanaged-command-closure`, and `task=showcases`; unrelated raw `true` remains allowed. Add fake plans proving an absent command refuses `crime=missing-managed-command` and a fake rustup missing `rust-src` refuses `crime=missing-toolchain-component` with channel `1.96.0`.

- [ ] **Step 2: Run RED**

Run the managed-precondition and Docker contracts. Expected: matching raw argv reaches transport and missing prerequisites reach their subjects.

- [ ] **Step 3: Implement command ownership refusal**

Before `sugar_bx_init`, when `host=bx` and no task was selected, ask `match-command` for an exact registered command prefix. Refuse only a claimed command:

```text
sugarbin: crime=unmanaged-command-closure command=make,test-showcases task=showcases replacement=select --task showcases
```

- [ ] **Step 4: Implement the plan runner**

Resolve named-task plans locally. In `sugar_bx_run_docker`, wrap the subject:

```bash
python /workspace/sugar/tools/sugar-build/preflight.py run \
  --plan-json "$SUGAR_BX_MANAGED_PRECONDITION_PLAN" \
  --artifact-root /opt/sugar -- "${command[@]}"
```

The runner checks commands with `shutil.which`, rustup components using the exact manifest channel, then artifacts. Each check prints its name, source, elapsed milliseconds, and result. On success it `os.execvp`s the subject; on missing authority it exits 70 first.

- [ ] **Step 5: Run GREEN and commit**

Run both focused contracts and `bash -n` on changed shell files. Commit `Refuse unmanaged showcase execution at entry`.

### Task 3: Make rebuild-lock failure finite

**Files:**
- Modify: `bin/sugarbin`
- Modify: `tests/sugarbin_rebuild_single_flight.sh`

**Interfaces:**
- Produces: `bin/sugarbin preflight-lock --stamp VALUE --bin NAME`, using the production acquire/release path.
- Produces: `crime=uncreatable-rebuild-lock-path`, `crime=unwriteable-rebuild-lock-state`, and `crime=unreclaimable-rebuild-lock`.

- [ ] **Step 1: Add both lock arms**

Use Python `subprocess.run(..., timeout=5)` from the shell contract. The writable private-cache fixture must acquire and release with no residue. The unreclaimable fixture plants a stale lock and shadows `rm` with a test executable that refuses that exact removal. Require exit 70, exactly one unreclaimable crime, exact path, `holder_pid=unknown`, and `heartbeat_age_s=999999`.

- [ ] **Step 2: Run RED**

```bash
bash tests/sugarbin_rebuild_single_flight.sh "$PWD"
```

Expected: the disposable command is absent or the planted state times out.

- [ ] **Step 3: Implement finite refusal**

Change lock-parent creation from degraded success to named refusal. Require PID and heartbeat writes after winning `mkdir`. After stale or no-heartbeat reclaim, require both successful removal and absence of the path before continuing; otherwise log once and return 70.

- [ ] **Step 4: Expose the real disposable cycle**

Dispatch `preflight-lock` after function definitions and before normal `main`. Bind globals, call the production acquire, call the production release, and return the actual status. Do not duplicate the lock algorithm.

- [ ] **Step 5: Run GREEN and commit**

Run the lock contract twice and `bash -n bin/sugarbin`. Commit `Terminate unreclaimable rebuild locks`.

### Task 4: Authenticate artifact ABI before subject execution

**Files:**
- Modify: `tools/sugar-build/preflight.py`
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `tests/sugarbin_docker_exec.sh`

**Interfaces:**
- Consumes: required-artifact manifest and plan `artifact-abi` checks.
- Produces: `crime=artifact-abi-incompatible` with artifact path and loader output.

- [ ] **Step 1: Add ABI twins**

Extend the managed pre-subject wrapper fixture. A fake `ldd` returning a normal libc mapping must allow the subject. A second fake returns nonzero with `version 'GLIBC_2.39' not found`; require exit 70, named ABI crime, artifact path, retained loader text, and no subject marker.

- [ ] **Step 2: Run RED**

Run `tests/sugarbin_docker_exec.sh`; expected: the incompatible twin reaches the subject or lacks the named reason.

- [ ] **Step 3: Implement ABI authentication once**

Put the ABI routine in `preflight.py` and invoke it from the transport-owned plan runner before `os.execvp`. Accept a non-ELF/static `ldd` result only when output says `not a dynamic executable`; refuse missing libraries and versioned loader failures. Never execute the artifact as a probe. Do not edit the checked-in image entrypoint in stage one: that source cannot affect already-published immutable images.

- [ ] **Step 4: Run GREEN and commit**

Run Docker, managed-precondition, and shell-tier wrapper contracts. Commit `Refuse incompatible managed artifacts before execution`.

### Task 5: Verify, publish, and land stage one

**Files:**
- Modify: the design spec only if verification reveals an actual correction.

**Interfaces:**
- Produces: stage-one PR and merge receipt.

- [ ] **Step 1: Run focused verification**

```bash
bash -n bin/sugarbin bin/lib/sugar-bx.sh \
  tests/sugarbin_managed_preconditions.sh tests/sugarbin_docker_exec.sh \
  tests/sugarbin_rebuild_single_flight.sh
bash tests/sugarbin_managed_preconditions.sh "$PWD"
bash tests/sugarbin_rebuild_single_flight.sh "$PWD"
bash tests/sugarbin_docker_exec.sh "$PWD"
git diff --check
```

Require nine discovered/predicted and zero uncovered, both lock arms, ABI twins, intentional current-image refusal, and the detached-lifetime non-claim.

- [ ] **Step 2: Verify scope and sealed receipt**

Confirm no Dockerfile/image digest changed, no file was deleted, no category/kind/label/taxonomy/residual bucket escaped the closed design vocabulary, and the closing-account digest remains exact.

- [ ] **Step 3: Rebase and publish**

Tree-compare against current main, rebase if needed, push the exact head, and open a PR with predicted `Epsilon R`, receipts, and non-claims. Do not force-push without separate authority.

- [ ] **Step 4: Merge under the standing rule**

Merge only if API MERGEABLE and every actual check that ran is green or absent. Verify API state `MERGED`, record merge SHA, re-check the closing-account digest, and report through Keyser with two Enters.
