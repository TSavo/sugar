# GeneratorConstructionV1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct Python generators as suspended machines and derive generator context-manager behavior mechanically from their typed transitions.

**Architecture:** `FunctionDef` authenticates generator shape from its already-materialized source children and produces a `SourceVisibleCallFrameV1` whose call allocates one `GeneratorConstructionV1`. The machine owns resume/send/throw/close transitions and `With` consumes those transitions directly, preserving `ExitSet` faces and leaving unsupported transitions typed-loud.

**Tech Stack:** Python 3.12+, immutable dataclasses, existing source-tree construction, `ExitSet`, pytest, battleaxe `bcargo`/`brun` validation.

## Global Constraints

- One construction path; no second evaluator and no `ast.*` switch.
- No contextlib, warning, decorator, callable, or manager name gate.
- Preserve `h = h(p)`, both guarded faces, and exhaustive-or-typed-LOUD behavior.
- No fabricated values, new side-door findings, panic catches, or timeout increase.
- Rebase on current `origin/main`, publish as T Savo, and do not merge.

---

### Task 1: Red Generator Construction Instrument and Transition Twins

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/scripts/generator_construction_law.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_generator_construction_law.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py`

**Interfaces:**
- Consumes: repository Python production roots and existing `ExitSet`/effect types.
- Produces: numeric `R_generator_construction`, a proven non-empty discovered denominator, and executable API requirements for `GeneratorConstructionV1`, `YieldEffect`, transition requests, termination, and typed transition gaps.

- [ ] **Step 1: Write the failing instrument and minimal allocation/resume twins**

The scanner must discover generator definitions from source structure, report generator call paths that still reduce through eager `SourceVisibleFunctionBodySugar`, and flag production references to contextlib/warning names in the new generator path. The API test imports `GeneratorConstructionV1`, allocates a renamed one-yield frame, resumes it, and asserts the exact yielded value plus successor coordinate.

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest --noconftest implementations/python/sugar-lift-py-tests/tests/test_generator_construction_law.py implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py -q`

Expected: FAIL because `generator_construction` and `YieldEffect` do not exist and `R_generator_construction > 0`.

- [ ] **Step 3: Record baseline JSON**

Run: `python3 implementations/python/sugar-lift-py-tests/scripts/generator_construction_law.py --json > /tmp/generator-construction-base.json`

Expected: nonzero `discovered`, nonzero `R_generator_construction`, and exit 1.

### Task 2: Suspended Machine and Mechanical With Derivation

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/generator_construction.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_call_frame.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_site_sugar.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/with_resource_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py`
- Test: `implementations/python/sugar-source-tree/tests/test_generator_context_manager_construction.py`

**Interfaces:**
- Consumes: `SourceVisibleCallFrameV1`, source-materialized statement Sugars, binding entries, and `ExitSet`.
- Produces: `GeneratorConstructionV1.allocate`, `resume`, `send`, `throw`, `close`; `YieldEffect(value, resume_coordinate)`; typed termination and transition-gap results; mechanical `With` routing.

- [ ] **Step 1: Implement allocation and resume minimally**

Add immutable typed construction/transition dataclasses. Allocation hashes the source frame CID, call-site coordinate, and bound binding coordinates into the instance coordinate. Resume reduces only to the first source-owned `Yield` boundary and carries the remaining suspended frame plus binding state.

- [ ] **Step 2: Verify allocation/resume GREEN**

Run the focused `test_generator_construction_v1.py` allocation and resume tests; expect PASS.

- [ ] **Step 3: Add failing send/throw/close and loud-boundary twins**

Tests require send to bind the prior yield expression result before continuing, throw to introduce the exact incoming typed effect and preserve completed/halted faces, close to inject generator termination mechanics, and second-yield/premature-return/opaque frames to return typed loud gaps.

- [ ] **Step 4: Implement send/throw/close through the same transition reducer**

All four public methods create a typed transition request and invoke one reducer. No method reparses source, switches on `ast.*`, or recognizes names. Unsupported statement/control shapes return `GeneratorTransitionGapV1` with owner, observed shape, requested transition, and replacement architecture.

- [ ] **Step 5: Verify transition GREEN**

Run: `python3 -m pytest --noconftest implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py -q`

Expected: every allocation/resume/send/throw/close and loud-boundary twin passes.

- [ ] **Step 6: Add failing renamed generator-manager integration twins**

Parse source containing an arbitrarily renamed generator manager without decorators. Assert enter binds the first yielded term, normal exit requires termination, exceptional exit throws the incoming effect and retains both `ExitSet` faces, and lying/two-yield/premature/opaque variants remain loud.

- [ ] **Step 7: Implement mechanical With consumption**

When the manager expression constructs `GeneratorConstructionV1`, `WithResourceSugar` uses resume for enter, resumes on completed body faces, throws each halted body's exact effect, and combines transition results via `ExitSet`. Existing non-generator authenticated resource behavior remains unchanged.

- [ ] **Step 8: Verify integration GREEN**

Run: `python3 -m pytest --noconftest implementations/python/sugar-source-tree/tests/test_generator_context_manager_construction.py implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py -q`

Expected: renamed truthful/lying and all loud boundary twins pass.

### Task 3: Floors, Battleaxe, Rebase, and Publication

**Files:**
- Modify: only files exposed by red/green cycles above.
- Receipt: `/tmp/generator-construction-head.json`

**Interfaces:**
- Consumes: completed construction path and baseline JSON.
- Produces: comparable `Delta R`, structural floor receipts, rebased verified commit, and open GitHub PR.

- [ ] **Step 1: Run focused structural floors**

Run the generator law, construction side-door law, construction panic-catch law, source constructor-door tests, and exact generator/context-manager twins. Require zero new side doors and zero panic catches.

- [ ] **Step 2: Run battleaxe validation**

Use repository battleaxe wrappers for the focused Python suite and the authoritative generator/pandas census. Run children sequentially if concurrency times out; do not count `non_native_red` as green and do not increase timeout configuration.

- [ ] **Step 3: Record head JSON and calculate Delta R**

Run the same scanner command and discovery scope used for `/tmp/generator-construction-base.json`, write `/tmp/generator-construction-head.json`, assert `discovered == completed > 0`, and subtract numeric `R_generator_construction` fields. If receipts are incomparable, report `Delta R` as unmeasured.

- [ ] **Step 4: Refresh and rebase**

Run `git fetch origin main`, rebase `agent/generator-construction-v1` onto `origin/main`, resolve only lane-owned conflicts, and rerun focused structural and battleaxe validation.

- [ ] **Step 5: Commit and publish without merging**

Commit with `T Savo <evilgenius@nefariousplan.com>`, push with upstream (or force-with-lease after rebase), open a ready-for-review PR against `main`, and report its number, rebased tip, validations, honest `Delta R`, and unmerged status.
