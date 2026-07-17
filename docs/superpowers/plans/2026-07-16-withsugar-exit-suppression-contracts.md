# WithSugar Exit Suppression Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct proof-bearing exit suppression contracts for the approved closed static subset.

**Architecture:** Installed-source call construction recognizes exact context-manager sources and produces an immutable suppression contract. `WithSugar` consumes only proven dispositions and leaves every other shape on its existing loud gap.

**Tech Stack:** Python 3.14, Sugar Python factory/floors, pytest.

## Global Constraints

- Never infer non-suppression from missing or runtime-dependent evidence.
- Preserve every existing panic/refusal outside the proven subset.
- Use focused tests only; no composed mints or corpus sweep.

---

### Task 1: Pin exit-contract discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_with_callsite_exit_contract.py`

**Interfaces:**
- Consumes: `WithSugar` reduction over a source-backed manager.
- Produces: red tests for suppressing, non-suppressing, and unresolved exits.

- [ ] Add tests whose bodies carry the same `ValueError` raise but whose exit contracts prove suppress, prove propagate, or cannot decide.
- [ ] Run only those tests and record the expected red result.

### Task 2: Construct and consume the static contract

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/with_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`
- Modify or create a focused floor module under `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/` only if a distinct value is required.

**Interfaces:**
- Consumes: exact `__exit__` body or exact `contextmanager` generator source.
- Produces: `suppresses(exception) -> bool` only for statically proven shapes; all other calls panic at the named `WithSugar` gap.

- [ ] Implement the smallest immutable contract for the proven subset.
- [ ] Route exact installed-source manager calls to that contract.
- [ ] Make `WithSugar` consume it without changing unknown-manager behavior.
- [ ] Run the focused discrimination tests until green.

### Task 3: Verify the real representative and publish

**Files:**
- Test: `implementations/python/sugar-lift-py-tests/tests/test_with_callsite_exit_contract.py`

**Interfaces:**
- Consumes: installed NumPy `numpy.f2py.tests.util.switchdir` source.
- Produces: a completed focused lift or the next independent loud frontier.

- [ ] Re-run `numpy/f2py/tests/test_f2py2e.py` in fatal-triage child mode.
- [ ] Run focused formatting, type checking, and WithSugar tests.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>`, push, and open a non-closing PR with `Part of #4698`.
