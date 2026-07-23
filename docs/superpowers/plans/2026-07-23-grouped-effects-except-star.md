# Grouped Effects and `except*` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct topology-preserving grouped raise effects and route `except*` by authenticated subtype partition through the one ExitSet effect router.

**Architecture:** Source `Raise` constructs immutable group trees from authenticated builtin group coordinates. The shared effect router partitions and regroups those trees; a distinct `TryStarSugar` sequences residual groups through handlers while ordinary `TrySugar` remains unchanged.

**Tech Stack:** Python typed source tree, Sugar floors/effects, ExitSet routing, pytest.

## Global Constraints

- Preserve group topology and every leaf occurrence identity.
- Use the merged builtin subtype floor; never match spelling.
- Keep matched and residual empty partitions explicit.
- Route through the shared ExitSet effect router only.
- Keep ordinary `except` and `except*` distinct.
- Unsupported or symbolic topology stays typed loud.
- Add no panic catch or construction side door.

---

### Task 1: Immutable grouped effect and authenticated partition

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/grouped_raise_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/authenticated_exception_type_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_grouped_raise_effect.py`

**Interfaces:**
- Produces `GroupedRaiseEffect.partition(expected, site) -> GroupedRaisePartition`.
- `GroupedRaisePartition.matched` and `.residual` are always explicit group roots.

- [ ] Write nested, partial, empty-face, identity, and lying-coordinate tests.
- [ ] Run them and verify missing grouped-effect imports fail.
- [ ] Implement recursive floor-based partition without flattening.
- [ ] Run the focused tests green and commit.

### Task 2: Source-authenticated grouped raise construction

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/grouped_raise_sugar.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Test: `implementations/python/sugar-source-tree/tests/test_try_sugar.py`

**Interfaces:**
- Consumes authenticated exception-group and leaf coordinates from `SourceUnit`.
- Produces `Incomplete(GroupedRaiseEffect)` through the ordinary `Raise` Sugar path.

- [ ] Replace the old loud `TryStar` fixture with a red grouped-raise construction test.
- [ ] Verify it fails because `TryStar`/group construction is absent.
- [ ] Add recursive group/leaf Sugar construction keyed by authenticated coordinates.
- [ ] Verify nested topology and leaf occurrence identity; commit.

### Task 3: One-router `except*` sequencing and regrouping

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect_router.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_star_sugar.py`
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Test: `implementations/python/sugar-source-tree/tests/test_try_sugar.py`

**Interfaces:**
- Produces `route_except_star(effect, expected, slot_id, site)` from the shared router.
- `TryStarSugar` passes residuals in handler order and regroups handler effects plus residuals.

- [ ] Add red tests for partial consumption, subsequent handlers, bare re-raise, handler-raised effects, and unmatched propagation.
- [ ] Verify each fails on the missing `TryStar` construction arm.
- [ ] Implement residual sequencing and identity-aware regrouping in the shared router.
- [ ] Run all try/grouped tests green; commit.

### Task 4: Permanent laws, rebase, and review PR

**Files:**
- Modify only if a truthful planted twin exposes an actual detector gap.

- [ ] Run grouped/try focused tests with the exact three-source `PYTHONPATH`.
- [ ] Run construction side-door and panic-catch laws; require `R=0` and zero auditor errors.
- [ ] Fetch and rebase onto current `origin/main`.
- [ ] Re-run all focused receipts after rebase.
- [ ] Push the branch and open a non-draft review PR; do not merge.
