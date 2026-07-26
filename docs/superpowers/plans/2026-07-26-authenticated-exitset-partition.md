# Authenticated ExitSet Partition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve producer-authenticated branch testimony through equal-destination normalization so the measured `make_doc` factoring gap cannot be constructed, while unauthenticated lookalikes still refuse.

**Architecture:** Replace the current definite-face set with DNF path testimony excluded from equality and repr. Conjunction extends every path with the new face; disjunction keeps both alternative paths; factoring proves two arms exclusive only when every cross-product path pair contains opposite faces of one authenticated partition.

**Tech Stack:** Python 3, frozen dataclasses, pytest, Sugar `ExitSet`/`GuardedProjection` construction.

## Global Constraints

- Base is current main `3ff6f44b6fef6563decbc6b1b311b7694b07a47b`.
- Testimony remains `compare=False, repr=False`.
- Exclusivity is never inferred by searching inside formula `or` nodes.
- Equal destinations still merge; `_destination_key` remains guard-insensitive.
- No product cap, materializing fallback, or observed-source special case.
- Delete the unreachable #6339 helpers instead of extending them.

---

### Task 1: Producer-driven discrimination twins

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py`

**Interfaces:**
- Consumes: `GuardedProjection`, `read_binding`, `ExitSet.factor_completed`.
- Produces: a truthful test that passes only if testimony survives a real equal-value producer merge, and a lying test that passes only if formula appearance remains insufficient.

- [ ] **Step 1: Write the truthful failing test**

Define a minimal `Sugar` leaf returning `Complete(value)`. Build a real
`GuardedProjection(slot, leaf, leaf)` whose two branches return the same value,
call `read_binding`, and assert normalization produced one completed destination
with two authenticated path alternatives. Combine that result with a sibling
completed arm carrying the opposite face of one surviving alternative and call
`factor_completed()`. Assert the factoring succeeds and retains both values.

- [ ] **Step 2: Write the lying failing test**

Construct the same visible guards directly with `Completed(g, ...)` and
`Completed(not_(g), ...)`, but provide no producer testimony. Assert
`ExitSetFactoringGap` by named exception.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
python -m pytest tests/test_exit_set_partition_testimony.py -q
```

Expected: the truthful producer test fails because
`guarded_binding_read_sugar.read_binding` mints no partition and normalization
cannot retain alternative paths. The lying test remains green.

- [ ] **Step 4: Commit the red instrument**

```bash
git add implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py
git commit -m "test: pin equal-value partition testimony merge"
```

### Task 2: Honest DNF testimony representation

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/exit_set.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py`

**Interfaces:**
- Consumes: `PartitionFace`.
- Produces: `PartitionPath = frozenset[PartitionFace]`,
  `PartitionPaths = frozenset[PartitionPath]`, helpers for conjunction,
  disjunction, and authenticated exclusivity.

- [ ] **Step 1: Replace definite faces with alternative paths**

Change `Completed` and `Halted` testimony to a `paths` field with default
`frozenset({frozenset()})`, still `compare=False, repr=False`. A bare arm has
one unconstrained path, not zero reachable paths.

- [ ] **Step 2: Implement propagation helpers**

Add:

```python
def _conjoin_paths(left: PartitionPaths, right: PartitionPaths) -> PartitionPaths:
    return frozenset(a | b for a in left for b in right)

def _disjoin_paths(left: PartitionPaths, right: PartitionPaths) -> PartitionPaths:
    return left | right

def _paths_exclusive(left: PartitionPaths, right: PartitionPaths) -> bool:
    return all(
        _path_pair_exclusive(a, b)
        for a in left
        for b in right
    )
```

`_path_pair_exclusive` returns true only for opposite sides of the same
`PartitionFace.partition`.

- [ ] **Step 3: Route every ExitSet transformation through those helpers**

`guarded(face)` conjoins a singleton face path. `sequence`, `and_finally`,
`and_exit`, and `and_exit_truthiness` conjoin testimony. `normalize` and
`factor_completed` disjoin testimony when guards are disjoined. Keep the field
out of equality and repr.

- [ ] **Step 4: Remove dead #6339 surface**

Delete `_partition_exclusive`, `_union_partition`, and
`ExitSet.with_partition_face`; scoped repo search must show zero occurrences.

- [ ] **Step 5: Update existing testimony tests**

Translate direct `faces` assertions to path alternatives. Preserve tests for
same-owner opposite sides, different owners, same side, equality/repr
invisibility, conjunction, and disjunction.

- [ ] **Step 6: Run focused tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_exit_set_partition_testimony.py -q
```

Expected: all tests pass, including the producer-driven truthful twin and
formula-lookalike lying twin.

### Task 3: GuardedProjection minting door

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/guarded_binding_read_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py`

**Interfaces:**
- Consumes: `partition(owner)` and `ExitSet.guarded(guard, face)`.
- Produces: producer-owned then/else testimony keyed by
  `("GuardedBindingRead", state.slot, read_site, guard)`.

- [ ] **Step 1: Mint the split at the producer**

Immediately after `guard = branch_result_guard(...)`, mint `then_face,
else_face = partition(...)`; pass each face into the existing true and false
`.guarded()` calls. Do not special-case values or source function names.

- [ ] **Step 2: Correct `_are_exclusive` documentation**

Replace only the false statement that one-level comparison covers all tower
shapes. Keep the sound-only and refuse-on-false contract verbatim.

- [ ] **Step 3: Run focused tests**

Run:

```bash
python -m pytest tests/test_exit_set_partition_testimony.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit implementation**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/exit_set.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/guarded_binding_read_sugar.py implementations/python/sugar-lift-py-tests/tests/test_exit_set_partition_testimony.py
git commit -m "fix: preserve authenticated partition paths"
```

### Task 4: Verification and handoff

**Files:**
- Verify: all changed files.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: attributable focused/full-package receipts and a narrow pushed branch.

- [ ] **Step 1: Print attribution guards**

```bash
python -c "import sugar_lift_py_tests as m; print(m.__file__)"
git rev-parse HEAD
```

The module path must point into this worktree and the SHA must equal the tested
tip.

- [ ] **Step 2: Run focused verification**

```bash
python -m pytest tests/test_exit_set_partition_testimony.py -q
```

- [ ] **Step 3: Run the full package suite**

```bash
python -m pytest
```

Report collection and outcome counts. Compare failure node sets to a
current-main baseline before making any regression claim.

- [ ] **Step 4: Self-review**

Run `git diff --check`, inspect the complete base-to-head diff, confirm the
dead helper names are absent in `exit_set.py`, and confirm only the spec, plan,
ExitSet, guarded-binding producer, and testimony tests changed.

- [ ] **Step 5: Commit plan or final adjustments**

Use repo-configured `Co-authored-by` then `Signed-off-by` trailers for every
commit and verify them with `git log -1`.

- [ ] **Step 6: Push and report**

Push `bumble/authenticated-partition-main` without merging. Report base SHA,
head SHA, exact test receipts, and that stableZero remeasurement remains a
separate combined-lanes step.
