# Bitwise-Or Guarded Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the decidable guarded set-union floor that currently stops one pandas representative at `owner=bitwise_or`.

**Architecture:** Add exact union to `SetValue`, then reuse `GuardedValue._map` to distribute bitwise-or across branch faces. Leave all unsupported combinations on the inherited loud floor and add no runtime effect.

**Tech Stack:** Python 3.14, pytest, Sugar Python floor values, FactoryPanic.

## Global Constraints

- Construct decidable evidence or panic loudly.
- A RuntimeEffect may represent only runtime-by-nature operands; this change adds none.
- No full-corpus sweep.
- Silent mass remains zero.

---

### Task 1: Specify exact and guarded set union

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_guarded_arithmetic_total.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_set_value.py`

**Interfaces:**
- Consumes: `SetValue.bitwise_or(other, site)` and `GuardedValue.bitwise_or(other, site)`.
- Produces: focused red tests for exact union, guarded distribution, and loud unsupported operands.

- [ ] **Step 1: Write failing exact-union and guarded-distribution tests**

Add tests asserting `SetValue(("a",)) | SetValue(("b",))` constructs the
ordered union and a guarded pair of sets distributes the same operation into
both faces.

- [ ] **Step 2: Run focused tests and verify RED**

Run:
`pytest tests/test_set_value.py tests/test_guarded_arithmetic_total.py -q`

Expected: `SetValue` and `GuardedValue` fall through to
`FactoryPanic owner=bitwise_or`.

### Task 2: Implement the minimum construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/set_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/guarded_value.py`

**Interfaces:**
- Consumes: existing `Complete`, `GuardedValue._map`, and floor-value equality.
- Produces: exact `SetValue` union and guarded face distribution.

- [ ] **Step 1: Implement `SetValue.bitwise_or`**

Return `Complete(SetValue(...))` only when the right operand is exactly a
`SetValue`; otherwise delegate to `super().bitwise_or`.

- [ ] **Step 2: Implement `GuardedValue.bitwise_or`**

Return `self._map("bitwise_or", other, site)`.

- [ ] **Step 3: Run focused tests and verify GREEN**

Run:
`pytest tests/test_set_value.py tests/test_guarded_arithmetic_total.py -q`

Expected: all focused tests pass, including the concrete unsupported
`FactoryPanic` discrimination.

### Task 3: Replay and publish

**Files:**
- No production files beyond Task 2.

**Interfaces:**
- Consumes: current pandas `tests/groupby/test_api.py`.
- Produces: bounded conservation receipt and non-closing PR.

- [ ] **Step 1: Replay the named representative**

Run `lift_file_payload` only on `pandas/tests/groupby/test_api.py`.

Expected: no `owner=bitwise_or`; either complete or a separately named loud
frontier.

- [ ] **Step 2: Run formatting and focused witness checks**

Run Black 26.5.1, `git diff --check`, the focused tests, and the registered
bitwise witness truthful/lying pair if one exists at the owning sugar.

- [ ] **Step 3: Commit, push, and open a draft PR**

Use author `T Savo <evilgenius@nefariousplan.com>`, body `Part of #4818`, and
never close/fix the issue in PR prose. Mark ready only after the bounded receipt
is recorded.

