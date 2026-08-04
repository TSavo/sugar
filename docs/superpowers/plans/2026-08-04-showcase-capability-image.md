# Showcase Capability Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish and select an immutable managed showcase image whose extra commands and Rust components are derived from the stage-one task closure, provision every declared profile-qualified artifact, and enforce the artifact ABI from inside the image before the showcase subject executes.

**Architecture:** `resolve_task_preconditions()` remains the sole derivation door. A new image-build projection filters that plan into command packages and exact Rust components, while a task-image record binds the resulting immutable digest and entrypoint protocol to `showcases` without adding undeclared extras to the shared capability image. The transport keeps its workspace preflight fallback for old images; only a task image declaring `managed-entrypoint/v1` receives the plan as entrypoint testimony and executes the baked verifier.

**Tech Stack:** Python 3.12 standard library, Bash, TOML, Docker Buildx, existing sugarbin/battleaxe transport.

## Global Constraints

- Derive `git` from `tasks.showcases.closure.required_commands`; do not add a second package roster.
- Derive `rust-src` and channel `1.96.0` from active showcase-adjacent `rust-toolchain.toml`; do not add a second component roster.
- Keep the workspace preflight fallback executable until the immutable task image advertises `managed-entrypoint/v1`.
- Resolve the nine profile-qualified closure artifacts exactly once into one manifest; ordinary task execution keeps `SUGAR_BINARY_ALLOW_BUILD=0` and never invents an implicit build fallback.
- Preserve the stage-one account at `R_precondition_axes_discovered=9`, `R_precondition_axes_predicted=9`, and `R_unpredicted_precondition_axes=0`; its planted unpredicted twin must still exit 70.
- Detached remote execution remains unsolved and receives no managed success claim.
- Preserve the closing-account JSON SHA-256 `20c96121eb1fe9715a5aa63dd74218eaefd15f5b52c6295378c91514fa5afaf1`.

---

### Task 1: Derive the task-image build closure

**Files:**
- Modify: `tools/sugar-build/contract.py`
- Create: `tools/sugar-build/build_task_image.py`
- Modify: `tools/sugar-build/Dockerfile`
- Modify: `tests/sugarbin_managed_preconditions.sh`

**Interfaces:**
- Consumes: `resolve_task_preconditions("showcases", "bx", repo_root)`.
- Produces: `resolve_task_image_build(name, repo_root) -> dict` with `aptPackages`, `rustComponents`, `rustToolchain`, and `target`.
- Produces: CLI `contract.py resolve-task-image-build TASK --repo-root PATH`.
- Produces: CLI `build_task_image.py TASK --tag IMAGE [--push|--load]`.

- [ ] **Step 1: Write the RED build-projection teeth**

Extend `tests/sugarbin_managed_preconditions.sh` to require this exact projection from the live plan:

```json
{
  "aptPackages": ["git"],
  "rustComponents": ["rust-src"],
  "rustToolchain": "1.96.0",
  "target": "showcases-closure",
  "task": "showcases"
}
```

Copy the repository to a private fixture, add a second command and component declaration, and prove both appear without changing production code. Plant two Rust channels and require a named `ContractError`, because one image stage cannot honestly claim two active toolchains.

- [ ] **Step 2: Run RED**

Run:

```bash
bash tests/sugarbin_managed_preconditions.sh "$PWD"
```

Expected: nonzero because `resolve-task-image-build` does not exist.

- [ ] **Step 3: Implement the minimal projection**

Filter only `command` and `toolchain-component` rows from the canonical precondition plan. Command names must satisfy the Debian package token grammar and become apt package names without a second mapping. All component rows must share one exact channel; otherwise refuse rather than choosing one.

Add a generic Docker target:

```dockerfile
FROM examples-closure AS showcases-closure
ARG MANAGED_APT_PACKAGES
ARG MANAGED_RUST_TOOLCHAIN
ARG MANAGED_RUST_COMPONENTS
RUN test -n "${MANAGED_APT_PACKAGES}" \
 && test -n "${MANAGED_RUST_COMPONENTS}" \
 && apt-get update \
 && apt-get install -y --no-install-recommends ${MANAGED_APT_PACKAGES} \
 && rm -rf /var/lib/apt/lists/* \
 && for component in ${MANAGED_RUST_COMPONENTS}; do \
      rustup component add --toolchain "${MANAGED_RUST_TOOLCHAIN}" "${component}"; \
    done
```

`build_task_image.py` obtains every build arg from `resolve_task_image_build`, invokes Docker Buildx with `--platform linux/amd64`, and never accepts caller-authored package or component overrides.

- [ ] **Step 4: Run GREEN and commit**

Run the managed-precondition shell contract, `python3 -m py_compile` on both Python files, and `git diff --check`. Commit `Derive showcase capability image inputs`.

### Task 2: Provision the profile-qualified artifact closure

**Files:**
- Modify: `bin/sugarbin`
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `tests/sugarbin_docker_exec.sh`

**Interfaces:**
- Consumes: `resolve-task` field `closure.artifacts`, preserving each `{profile, name}` pair.
- Produces: `sugar_bx_profiled_artifact_build_script(SPEC)` and `sugar_bx_build_profiled_artifacts_docker(IMAGE, SPEC)`.
- Produces: one `required-artifacts.json` containing every unique declared artifact name.

- [ ] **Step 1: Write RED mixed-profile transport teeth**

The fake Docker harness must show one artifact resolver container before the task container. Its command must carry `release:sugar` and all eight `debug:*` rows from the resolved task closure, emit one manifest, and keep `SUGAR_BINARY_ALLOW_BUILD=0`, `SUGAR_BINARY_PUBLISH=0`, and the shelf mount read-only. The task container must receive both the artifact directory and manifest.

- [ ] **Step 2: Run RED**

Run `bash tests/sugarbin_docker_exec.sh "$PWD"`. Expected: the showcase task launches no artifact resolver because `tasks.showcases.binaries` is intentionally empty.

- [ ] **Step 3: Implement profile-aware resolution once**

Serialize the validated closure rows as `profile:name` tokens. The production writer invokes `bin/sugarbin --profile "$profile" --bin "$name"` for each row and appends each checksum to one atomic manifest. Refuse duplicate names; never collapse the rows to the caller-wide `--profile` value. Keep the existing unprofiled builder unchanged for other tasks.

- [ ] **Step 4: Run GREEN and commit**

Run the Docker shell contract twice, `bash -n bin/sugarbin bin/lib/sugar-bx.sh`, and `git diff --check`. Commit `Provision declared showcase artifacts`.

### Task 3: Move managed preflight into the published image without an enforcement gap

**Files:**
- Modify: `sugar-build.toml`
- Modify: `tools/sugar-build/contract.py`
- Modify: `tools/sugar-build/Dockerfile`
- Modify: `tools/sugar-build/entrypoint.sh`
- Modify: `bin/sugarbin`
- Modify: `bin/lib/sugar-bx.sh`
- Modify: `tests/sugarbin_docker_exec.sh`
- Modify: `tests/test_sugar_build_contract.py`

**Interfaces:**
- Produces: optional `[task-images.showcases]` with immutable `reference` and `preflight = "managed-entrypoint/v1"`.
- Produces: `resolve_task_environment(name) -> dict` with task capabilities, immutable image, and preflight protocol.
- Consumes: `SUGAR_BX_MANAGED_PRECONDITION_PLAN` only when the selected task-image protocol is `managed-entrypoint/v1`.

- [ ] **Step 1: Write RED protocol-selection and entrypoint twins**

Require an immutable task-image reference and reject mutable tags or unknown protocols. In the fake Docker harness, an old image with no task-image record must still invoke `/workspace/sugar/tools/sugar-build/preflight.py`; a `managed-entrypoint/v1` image must pass the canonical plan as environment and invoke the raw subject. Exercise the real entrypoint with the installed verifier path: a compatible artifact reaches a marker, while a planted GLIBC mismatch exits 70 before the marker and preserves `crime=artifact-abi-incompatible` plus loader output.

- [ ] **Step 2: Run RED**

Run the Docker and managed-precondition shell contracts. Expected: the entrypoint never calls a baked verifier and the resolver has no task-image protocol.

- [ ] **Step 3: Bake and select the verifier**

Copy `preflight.py` into `/usr/local/lib/sugar/managed-preflight.py` in `showcases-closure`. At the end of the entrypoint, execute it with the canonical plan, `/opt/sugar`, and the subject argv when the plan environment is present. `sugar_bx_run_docker` selects this path only from authenticated task-image metadata; otherwise it preserves the workspace wrapper exactly.

- [ ] **Step 4: Run GREEN and commit before publication**

Run both shell contracts, the focused contract test through `bin/bpytest`, `bash -n`, `py_compile`, and `git diff --check`. Commit `Bake managed preflight into showcase image`.

### Task 4: Publish, pin, and execute the satisfying image

**Files:**
- Modify: `sugar-build.toml`
- Test: `tests/sugarbin_managed_preconditions.sh`
- Test: `tests/sugarbin_docker_exec.sh`

**Interfaces:**
- Consumes: `build_task_image.py showcases --push --tag ghcr.io/tsavo/sugar-env:showcases-<commit>`.
- Produces: immutable `ghcr.io/tsavo/sugar-env@sha256:<digest>` under `[task-images.showcases]`.

- [ ] **Step 1: Publish on battleaxe**

Run the tracked build wrapper through the ambient battleaxe route in the foreground, poll its log without detaching, and push the task image. Read the registry digest with `docker buildx imagetools inspect`; never derive a digest from a local image ID.

- [ ] **Step 2: Pin the immutable task image**

Record the exact registry digest and `preflight = "managed-entrypoint/v1"`. Re-run contract teeth proving the showcase task resolves that digest while `examples-gate` retains its prior shared capability image.

- [ ] **Step 3: Prove the restored subject edge**

Run the single active std-core shard using the named task with `SHOWCASE_SHARD_COUNT=46` and `SHOWCASE_SHARD_INDEX=9`, forwarded through sugarbin. Require the preflight to pass `git`, `rust-src`, and all artifact ABI rows before `examples/std-core-showcase/run.sh` prints its subject witness. A semantic red after that point is discovery; success of the entrance is established by reaching the subject.

- [ ] **Step 4: Re-run the stage-one falsifier and final hygiene**

Require the live nine-axis account to remain 9/9/0 and the planted unpredicted twin to exit 70. Verify the closing-account digest, tree diff, no deletions, `bash -n`, `py_compile`, focused shell contracts, and `git diff --check`.

- [ ] **Step 5: Commit, push, and open the PR**

Commit `Publish managed showcase capability image`, push without force, and open a main-targeted PR. The body must distinguish early-refusal restoration from showcase semantics, name the published digest, state that detached lifetime remains unsolved, and report the exact stage-one account plus the single-shard subject-edge result.
