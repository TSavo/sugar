# Ground False Assertion Exceptional Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the exact Python `AssertionError` exit for a ground false assertion.

**Architecture:** Reuse the existing `RaiseValue` control-flow substrate through
a focused ground-assertion constructor. Route only the proved-false Boolean
floor through it.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Global Constraints

- No RuntimeEffect constructor or empty-success arm.
- Ground true and symbolic assertion behavior stays unchanged.
- Uncited or absolute source loci remain loud.
- Use the worktree-local `.venv-lane`.
- Receipt is bounded; no full-corpus sweep.

### Task 1: Pin the exact exceptional exit

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/ground_assertion_error.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/false_bool_literal_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_truthiness.py`

**Interfaces:**
- Consumes: a source-cited assertion site.
- Produces: `Complete(RaiseValue(RaiseEffect("AssertionError", ...)))`.

- [ ] Add a failing test expecting `assert 0` to reduce to `RaiseValue`.
- [ ] Keep the `assert 1` discrimination arm green.
- [ ] Add matching and wrong-handler tests.
- [ ] Run the exact tests and record the red owner panic.
- [ ] Implement the minimal source-cited constructor and delegate the false arm.
- [ ] Run the focused tests green.

### Task 2: Witness and named receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_truthiness.py`

**Interfaces:**
- Produces: truthful SAT and wrong-exception-class UNSAT evidence.

- [ ] Add and run the real-solver witness.
- [ ] Run the RuntimeEffect constructor-site invariant.
- [ ] Replay `numpy/_core/tests/test_errstate.py`.
- [ ] Record conservation and `silent=0`.
- [ ] Run Black 26.5.1 and commit as T Savo.
