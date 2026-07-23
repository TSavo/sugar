# Construction-Occurrence Object Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated construction-occurrence identity and immutable attribute-field versions through Sugar's sole temporal binding path.

**Architecture:** Closed content-addressed coordinate/version values live in a focused `object_identity.py` module. Constructed call-result nodes carry those values through ordinary `BindingEntryV1.state`; `Call`, `Assign`, and `Attribute` only project or evolve authenticated testimony and never derive identity from binding owners or class/name shape.

**Tech Stack:** Python 3.12, dataclasses, Sugar source-tree construction, pytest, `bin/bpytest`, `bin/brun`, battleaxe pandas census.

## Global Constraints

- Attribute places ship; subscript places remain typed-loud.
- Identity is allocation definition plus exact call occurrence plus construction-context generation plus source/artifact CIDs, or an authenticated opaque-result coordinate from the call occurrence.
- Assignment copies object coordinates; distinct call occurrences remain distinct.
- Field state is keyed by object coordinate plus attribute-field coordinate and every mutation appends an immutable prior-linked version.
- Opaque calls invalidate only affected reachable field knowledge; unknown alias escape stays typed-loud.
- No `BindingEntryV1`-owner, type, spelling, equality, field-content, class, or vendor identity gate.
- One temporal binding model, `h = h(p)`, no fabrication, zero new side doors, zero panic catches, and no timeout increase.
- Heavy validation runs only on battleaxe.
- Rebase on current `origin/main` immediately before review/push; do not self-merge.

---

### Task 1: Close and test the coordinate/version substrate

**Files:**
- Create: `implementations/python/sugar-source-tree/src/sugar_source_tree/object_identity.py`
- Create: `implementations/python/sugar-source-tree/tests/test_object_identity_v1.py`

**Interfaces:**
- Produces: `SourceObjectCoordinateV1.mint(...)`, `OpaqueObjectCoordinateV1.mint(...)`, `AttributeFieldCoordinateV1.mint(...)`, `AttributeFieldVersionV1.mint(...)`, and each type's `decode()`/`wire()`.
- Invariant: every decoder accepts an exact closed wire shape and recomputes its CID from the complete preimage.

- [ ] Write tests that mint two source coordinates at different call fragments and assert different CIDs; mint aliases from the same wire and assert equality; mint an opaque coordinate and assert its wire contains no fields or behavior.
- [ ] Add mutation twins that alter allocation, occurrence, generation, source/artifact CID, selector, prior CID, stored-value testimony, and version CID; assert `BindingProvenanceGap`.
- [ ] Run `bin/bpytest implementations/python/sugar-source-tree/tests/test_object_identity_v1.py -q`; expect collection success and failures because `object_identity` is absent.
- [ ] Implement frozen exact-wire dataclasses whose `mint` and `decode` both compute `cid_of_json(preimage)`; use tagged variants rather than optional source/opaque fields.
- [ ] Re-run the focused test; expect all tests passing, then commit `Add construction occurrence object coordinates`.

### Task 2: Make acceptance and side-door instruments red first

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/verdict_matrix.json`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/version_flow.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/distinct_version_flow.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/selective_opaque_invalidation.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/opaque_result_identity.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/unknown_alias_escape.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/subscript_loud.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_object_field_flow_acceptance.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_construction_side_door_law.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/construction_side_door_law.py`

**Interfaces:**
- Produces: a closed matrix naming every approved acceptance invariant and a structural scanner axis for forbidden object-identity side doors.
- Consumes: the coordinate/version wire interfaces from Task 1.

- [ ] Add truthful, lying, and renamed structural fixtures for every approved acceptance behavior; make subscript and unknown escape explicit loud cases.
- [ ] Replace the broad strict-xfail positive test with exact per-case target assertions and add direct forgery tests for coordinate/version wires.
- [ ] Plant forbidden binding-owner identity, class/name/vendor dispatch, ambient object table, generic fallback, panic catch, and fabricated subscript implementations in scanner fixtures; require each offender and replacement shape to be reported.
- [ ] Run the acceptance and scanner tests through `bin/bpytest`; record the expected red acceptance count while planted scanner twins pass.
- [ ] Commit `Test construction occurrence object identity acceptance` without weakening the red target.

### Task 3: Carry identity and immutable attribute state through the sole path

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/binding_state.py` only if a closed state projection hook is required; do not add another map.
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/attribute_place_value.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/attribute_place_sugar.py`
- Modify: nearby `__init__.py` exports only where required by the kit registry.

**Interfaces:**
- Produces: an object-bearing constructed expression with `object_coordinate`, immutable tuple of attribute versions, `with_attribute_store(...)`, `attribute_field(...)`, and `invalidate_fields(...)`.
- Consumes: existing call-definition/source-oracle testimony and exact call `SourceFragment`; never consumes a destination binding coordinate as identity authority.

- [ ] Add a direct failing test proving `Call._construct_sugar` is invoked once and the exact occurrence fragment—not the destination binding—is the coordinate preimage.
- [ ] Implement source versus opaque occurrence minting at the sole call construction boundary, using authenticated resolved-definition/source/artifact testimony where present and opaque occurrence otherwise.
- [ ] Add failing alias and distinct-occurrence tests, then make ordinary assignment/substitution copy the object-bearing state unchanged.
- [ ] Add failing store/read/version-chain tests, then implement attribute store evolution as frozen prior-linked versions and attribute read projection after complete validation.
- [ ] Add failing descriptor/custom allocation/`__setattr__` and subscript tests; keep each typed-loud unless behavior construction is present.
- [ ] Run the focused acceptance, runtime binding, Assign, Call, and construction side-door tests through `bin/bpytest`; expect green and `R_construction_side_doors=0`.
- [ ] Commit `Thread immutable attribute state by object occurrence`.

### Task 4: Selective opaque invalidation and measured pandas delta

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/measure_binding_assignment_frontier.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_object_field_flow_acceptance.py`

**Interfaces:**
- Produces: call affected-set construction over authenticated argument coordinates; exact invalidation of reachable field knowledge; numeric base/head object-field census JSON.
- Invariant: inability to construct the affected alias set yields a typed gap, never global clearing or silent preservation.

- [ ] Write a failing twin where an opaque call receives one of two objects and only that object's known field becomes unavailable.
- [ ] Write a failing unknown-alias-escape twin and require typed-loud.
- [ ] Implement affected-set projection from authenticated call arguments and immutable invalidation markers for only those coordinates.
- [ ] Extend the census to emit discovered/completed/timeout/panic/non-native-red denominators plus per-outcome transition counts; tests must reject incomplete or zero denominators.
- [ ] Run focused tests through `bin/bpytest`; commit `Invalidate only opaque call affected fields`.
- [ ] On battleaxe, run identical base/head census commands with the same pandas artifact and timeout, capturing JSON and logs under a branch-specific remote receipt directory.
- [ ] Compare numeric JSON fields and record honest `Delta R`; if discovered does not equal completed or timeout/panic floors rise, report the measurement as incomplete rather than zero.

### Task 5: Rebase, verify, review, and publish without merging

**Files:**
- Modify: implementation/tests only as required to resolve current-main conflicts without changing the ruling.
- Create: PR body in a temporary file outside the repository.

**Interfaces:**
- Produces: one draft PR based on current `origin/main`, with focused receipts, battleaxe receipts, honest `Delta R`, predicted `Epsilon R`, and explicit unmerged status.

- [ ] Fetch `origin/main`, rebase the branch, and resolve conflicts by preserving current-main sole-path construction plus this plan's occurrence identity.
- [ ] Re-run the complete focused acceptance and side-door commands on battleaxe after the rebase; inspect exit codes and exact pass/fail counts.
- [ ] Run `git diff --check`, adds-only/vocabulary searches for forbidden owner/class/name/vendor identity gates, panic catches, ambient maps, fabricated subscript handling, and timeout changes.
- [ ] Review `git diff origin/main...HEAD` requirement by requirement; correct all critical/important findings and re-run affected tests.
- [ ] Confirm author/committer is `T Savo <evilgenius@nefariousplan.com>`, working tree is clean, and branch is still unmerged.
- [ ] Push with upstream tracking and open a draft PR targeting `main`; do not merge it.
- [ ] Report the PR number immediately with branch/head SHA, rebase base SHA, focused/battleaxe receipts, numeric `Delta R`, floors, and any honest residuals.
