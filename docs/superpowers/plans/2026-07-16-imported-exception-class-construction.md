# Imported Exception Class Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact imported Python exception subclasses so `RaiseSugar` receives an authenticated `ExceptionValue`.

**Architecture:** Extend installed-source value resolution with a conservative exception-ancestry proof and immutable exception-class floor. Reuse the existing CallSugar-to-ExceptionValue and RaiseSugar-to-RaiseValue path.

**Tech Stack:** Python 3.14, Python AST, Sugar Python floors, pytest.

## Global Constraints

- Never infer exception identity from spelling alone.
- Missing or ambiguous ancestry remains the existing loud named gap.
- Use focused tests and child triage only; no composed mint or gate.

---

### Task 1: Pin imported exception discrimination

**Files:**
- Test: `implementations/python/sugar-lift-py-tests/tests/test_imported_exception_class_floor.py`

**Interfaces:**
- Consumes: exact temporary installed-source modules.
- Produces: red good/bad twins for imported exception construction.

- [ ] Add an imported `CustomError(ValueError)` good twin and imported `Ordinary` bad twin.
- [ ] Assert the good twin reaches `RaiseValue` and the bad twin retains `RaiseSugar`'s named panic.
- [ ] Run the focused tests and record the expected red.

### Task 2: Construct exact exception ancestry

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/exception_class_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_sugar.py`

**Interfaces:**
- Produces: `ExceptionClassValue(qualified_name: str)` only for source-proven exception subclasses.

- [ ] Implement the immutable floor and bounded, cycle-safe ancestry proof.
- [ ] Return it from exact installed-source class resolution.
- [ ] Make CallSugar construct `ExceptionValue` from it.
- [ ] Run good/bad twins green.

### Task 3: Verify representative and publish

**Files:**
- Test: focused tests above.

**Interfaces:**
- Consumes: installed pandas 3.0.3 `core/dtypes/base.py`.
- Produces: child-triage terminal receipt.

- [ ] Re-run the representative child and record completion or the next independent named frontier.
- [ ] Run Black, the type ratchet, and focused tests.
- [ ] Commit as T Savo, push, and open a non-closing PR with `Part of #4704`.

