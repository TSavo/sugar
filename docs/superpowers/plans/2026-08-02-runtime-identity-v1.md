# Runtime Identity V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every measured control-effect recensus body cryptographically bind the exact authenticated CPython runtime that produced it.

**Architecture:** `sugar_lift_py_tests.authenticated_pytest` remains the runtime authority and projects one `runtimeIdentity/v1` wire value plus a path-independent runtime CID. Recensus workers authenticate before touching the corpus, partials carry the identity, and compose recomputes and agrees the identity before including it in the body CID seal domain. Every failure stays instrument-level Unmeasured.

**Tech Stack:** Python 3.12.13, stdlib `sys`/`sysconfig`/`platform`/`hashlib`, existing BLAKE3-512 canonicalizer, pytest, battleaxe `bin/bpytest`.

## Global Constraints

- Required runtime is derived only from `sugar-build.toml` and equals `cpython-3.12.13` on this pin.
- Host executable paths remain testimony but are excluded from `runtimeCid`.
- The resolved base executable bytes are SHA-256 hashed.
- Runtime authentication precedes corpus selection, demand work, checkpoints, and stages.
- `runtimeIdentity` and `runtimeCid` remain inside `bodyCid`; `sourceStamp` is insufficient.
- Identity failure or disagreement emits only Unmeasured and never `frontierWidth`.
- Never import `no_call_body_attribution.AUTHENTICATED_RUNTIME`.
- Do not run a corpus width measurement until this and the With entrance repair have landed.

---

### Task 1: Runtime identity authority

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/authenticated_pytest.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_runtime_identity_v1.py`

**Interfaces:**
- Produces: `RuntimeIdentityV1.to_wire()`, `observe_runtime_identity_v1()`, `runtime_cid_for_identity()`, `authenticate_runtime_identity_v1()`.
- Consumes: existing `interpreter_identity()`, `declared_interpreter_runtime()`, and `authenticate_interpreter_runtime()`.

- [ ] **Step 1: Write moved-identical and changed-byte red twins**

  Create two temporary base executable files with identical bytes and distinct paths; assert equal executable hashes and `runtimeCid` while path testimony differs. Change only one file's bytes and assert both hashes differ.

- [ ] **Step 2: Write schema and failure teeth**

  Assert the complete observed wire fields, required runtime, path exclusion, missing executable refusal, and mismatch preservation of the fully observed identity.

- [ ] **Step 3: Run the new test file red on battleaxe**

  Run `./bin/bpytest implementations/python/sugar-lift-py-tests/tests/test_runtime_identity_v1.py -q`. Expected: collection/import failure because the v1 authority does not exist.

- [ ] **Step 4: Implement the authority**

  Add a frozen identity value, chunked SHA-256 hashing, canonical path-free CID preimage, structural wire validation, and authentication through the existing interpreter door. Replace `authenticate_environment()`'s basic runtime check with this full authenticated observation so plan-time corpus resolution hashes the runtime first.

- [ ] **Step 5: Run Task 1 tests green and commit**

  Run the new file plus `test_measured_corpus_is_authenticated.py` and `test_repo_root_door.py` on battleaxe; commit only authority and tests.

### Task 2: Partial and compose refusal contract

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_frontier_attestation_seal.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_board_number_meanings.py`

**Interfaces:**
- Consumes: authenticated runtime attestation from Task 1.
- Produces: runtime-bound shard partials, unmeasured envelopes, and sealed boards.

- [ ] **Step 1: Add consumer-first red teeth**

  Add tests proving a missing partial identity, a non-recomputable `runtimeCid`, two individually valid but disagreeing shard identities, and absent compose identity all refuse without width. Add a truthful test proving identity is present and changing a semantic identity field changes the sealed `bodyCid`; changing only path testimony preserves `runtimeCid`.

- [ ] **Step 2: Run compose tests red on battleaxe**

  Run `test_frontier_attestation_seal.py` and `test_board_number_meanings.py`. Expected: new tests fail because partials and compose do not yet validate runtime identity.

- [ ] **Step 3: Bind partials and unmeasured envelopes**

  Extend `mint_partial` so runtime testimony is required for measured status and participates in `partialCid`. Extend `unmeasured_envelope` to carry resolved identity or a separate `runtimeIdentityFailure`, never an unavailable marker.

- [ ] **Step 4: Bind compose and board seals**

  Require the compose process identity, validate and agree every partial CID, propagate identity through every refusal, place identity fields in the measured body before conservation minting, and leave them in the `bodyCid` preimage.

- [ ] **Step 5: Run compose tests green and commit**

  Run both focused files on battleaxe, inspect the full output and exit, then commit the compose contract.

### Task 3: Early recensus and compose CLI authentication

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_recensus_runtime_identity_gate.py`

**Interfaces:**
- Consumes: Task 1 authority and Task 2 envelope/compose arguments.
- Produces: early mismatch/failure artifacts and authenticated k=1/shard execution.

- [ ] **Step 1: Write ordering and lying twins red**

  Assert a wrong runtime returns Unmeasured before an absent corpus is inspected or any checkpoint/stage path is created; assert a hash-resolution failure emits `runtimeIdentityFailure`; assert ordinary later refusal retains resolved runtime testimony. Add a compose CLI test proving runtime refusal happens before plan/partial reads.

- [ ] **Step 2: Run the gate file red on battleaxe**

  Run the new test file. Expected: failure because runtime authentication occurs after corpus path handling or does not produce the required envelope.

- [ ] **Step 3: Implement the preflight**

  Resolve required and observed identities immediately after parsing. On mismatch or resolution failure, write only the diagnostic unmeasured envelope to the requested result path and return the unmeasured exit. Pass authenticated testimony into shard mint and k=1 compose. Authenticate compose CLI before reading input artifacts.

- [ ] **Step 4: Run gate and integration tests green and commit**

  Run Task 3 tests and the complete Task 1/2 set on battleaxe; commit the entry wiring.

### Task 4: Exact branch verification and handoff

**Files:**
- Verify all files changed by Tasks 1-3.

**Interfaces:**
- Produces: a pushed runtime v1 branch ready for Kujan; no corpus number.

- [ ] **Step 1: Verify branch structure and floors**

  Confirm the branch is based on exact main, contains no With repair duplication, imports no floor-only runtime constant, deletes no tests/files, and adds no skips/xfails.

- [ ] **Step 2: Run the full focused runtime/compose set on battleaxe**

  Capture the unpiped exit and collected/pass counts. Do not infer a corpus result.

- [ ] **Step 3: Push and report**

  Push `keaton/runtime-identity-v1`; report the exact SHA, commands, counts, observed runtime field reproduction, and explicit nonclaim that no `frontierWidth` exists before both prerequisite branches land.
