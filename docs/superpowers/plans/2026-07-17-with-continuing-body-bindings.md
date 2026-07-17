# With Continuing-Body Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve bindings constructed by an actually continuing `with` body so the enclosing Python statement sequence can reduce them honestly.

**Architecture:** `WithSugar` will inspect the reduced body's continuation and project changed terminal-scope bindings as `ScopeRebind` support. It will not scan AST nodes, synthesize ambient values, or alter the existing raising-body and `__exit__` refusal paths.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift factory, real Sugar mint/prove witness harness.

## Global Constraints

- Part of #4696; never closes or fixes the whole issue.
- Runtime-dependent, opaque, or incomplete construction stays loud.
- Never weaken a panic or emit partial success.
- No full corpus census and no pre-existing type-ratchet gate.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Pin continuing-body scope projection

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_with_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/with_sugar.py`

**Interfaces:**
- Consumes: `SugarBody.reduce(ctx)`, `BlockSugar.reduce_with_scope(ctx)`, `FloorValue.follow_rest()`, and `TemporalContext.bindings`.
- Produces: `_reduce_continuing_body(body, ctx) -> Outcome` and changed-binding `ScopeRebind` contributions.

- [ ] **Step 1: Add the failing discrimination**

Add a test that composes:

```python
with manager:
    result = 5
return result
```

under a coordinate-only `CallSiteValue` manager and expects `TermValue(5)`.

- [ ] **Step 2: Add the loud bad twin**

Compose the same `with` body with `pass` instead of the assignment and assert a
`FactoryPanic` owned by `TemporalContext`, observed `result`.

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv-residual/bin/pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_with_sugar.py::test_continuing_with_body_projects_constructed_binding \
  implementations/python/sugar-lift-py-tests/tests/test_with_sugar.py::test_continuing_with_body_does_not_invent_missing_binding
```

Expected: the constructed arm fails at `TemporalContext(result)`; the bad twin
passes by remaining loud.

- [ ] **Step 4: Implement reduced-scope projection**

At the empty `remaining` arm of `WithSugar._enter_items`, reduce the body
normally. If it continues, obtain the body terminal scope, compare it with the
incoming body context, and append `ScopeRebind` entries for changed bindings.
If it exits, return the original outcome unchanged.

- [ ] **Step 5: Verify GREEN and regression**

Run the two discrimination tests, then all of `test_with_sugar.py` and
`test_with_callsite_exit_contract.py`.

### Task 2: Move the production witness onto the new seam

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/with_sugar.py`

**Interfaces:**
- Consumes: `WithSugar.witnesses()` and `run_source_through_real_solver`.
- Produces: `with_binding_return` truthful/lying pair whose return occurs after
  the `with`.

- [ ] **Step 1: Change the witness pair**

Use:

```python
def A(z):
    with z.lock():
        result = 1
    return result
```

Truthful asserts `A(5) == 1`; lying asserts `A(5) == 0`.

- [ ] **Step 2: Run the real solver witness**

Resolve/build the worktree-local debug Sugar binary, then run both witness arms
through `run_source_through_real_solver`. Require truthful `sat`, lying `unsat`,
and `WithSugar` selected on both arms.

### Task 3: Produce the bounded representative receipt and publish

**Files:**
- No additional production files.

**Interfaces:**
- Consumes: `corpus_fatal_triage.py --child-file`.
- Produces: named before/after owner accounting for the selected representative.

- [ ] **Step 1: Replay the representative**

Run `pandas/tests/frame/methods/test_select_dtypes.py` through the child triage
door. Require `TemporalContext(result)` to disappear; record completion or the
distinct loud next owner.

- [ ] **Step 2: Record honest residuals**

Replay `pandas/tests/copy_view/test_astype.py` and
`numpy/_core/tests/test_datetime.py` only as bounded residual telemetry. Do not
modify their mechanisms in this PR.

- [ ] **Step 3: Commit and publish**

Commit with author `T Savo <evilgenius@nefariousplan.com>`, push
`temporal-context-residual-bindings`, and open a draft PR whose body starts
`Part of #4696` and never closes the issue.

- [ ] **Step 4: Rebase and mark ready**

Rebase onto current `origin/main`, rerun the focused discrimination, real
witness, and named representative, force-push, then mark the PR ready.

