# Static For Post-Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve bindings proved by the final iteration of a statically non-empty `for`.

**Architecture:** Derive post-loop bindings from the initial and final reduced
temporal scopes, not from assignment ASTs. Reuse `ScopeRebind` as the existing
scope testimony.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Global Constraints

- No RuntimeEffect constructor or empty-success arm.
- Empty and runtime-selected iterables do not gain definite bindings.
- Use only reduced semantic scope outcomes.
- Use the worktree-local `.venv-lane`.
- No full-corpus sweep.

### Task 1: Static non-empty post-scope

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/for_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_for_sugar.py`

**Interfaces:**
- Consumes: initial and final `TemporalContext.bindings`.
- Produces: changed/new `ScopeRebind` contributions.

- [ ] Add a red three-element last-value test and empty-list bad twin.
- [ ] Run red and confirm `TemporalContext(x)`.
- [ ] Export final reduced scope delta for non-empty static iterations.
- [ ] Run focused tests green.
- [ ] Add truthful/lying real-solver witness.

### Task 2: Receipt

- [ ] Run the focused ForSugar tests and witness.
- [ ] Run the RuntimeEffect constructor-site invariant.
- [ ] Replay `numpy/_core/tests/test_datetime.py`.
- [ ] Record conservation and `silent=0`.
- [ ] Run Black 26.5.1 and commit as T Savo.
