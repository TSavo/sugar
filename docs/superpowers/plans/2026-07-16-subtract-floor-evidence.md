# Subtract Floor Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live subtract-floor corpus panics with exact native/set evidence or authenticated runtime effects.

**Architecture:** Extend the true owner floors rather than changing SubtractOpSugar dispatch. Exact numeric-symbolic and set-set cases construct values; call-result-dependent cases share a named `SubtractRuntimeEffect` boundary.

**Tech Stack:** Python 3.14, pytest, Sugar ProofIR terms, real Sugar solver witness harness.

## Global Constraints

- Never translate an unsupported subtraction into unwarranted success.
- Opaque runtime dispatch stays a loud named effect.
- Replay only the 11 retained names; do not run a full corpus sweep.
- Do not gate on the pre-existing pyright/type-ratchet wall.

---

### Task 1: Pin exact and runtime subtraction red

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_subtract_op.py`

**Interfaces:**
- Consumes: existing floor values and `SubtractOpSugar` dispatch.
- Produces: red assertions for native coordinate, exact set difference, and authenticated runtime effect.

- [ ] Test `TermValue(4) - SymbolicValue(n)` equals `SymbolicValue(-(4,n))`.
- [ ] Test `{left, shared} - {shared}` equals `{left}`.
- [ ] Test concrete/comprehension/native left operands with call-result rights all return `SubtractRuntimeEffect` witnessed over both operands.
- [ ] Run the focused tests and retain the current FactoryPanics as RED evidence.

### Task 2: Implement the truthful owner floors

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/subtract_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/term_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/set_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/comprehension_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/native_callable_value.py`

**Interfaces:**
- Consumes: `runtime_effect_witness`, each operand's `to_term`, and existing native symbolic subtraction.
- Produces: exact values or `Incomplete(SubtractRuntimeEffect)`.

- [ ] Define and export `SubtractRuntimeEffect` plus a single helper that builds its witnessed two-operand boundary.
- [ ] Route numeric-symbolic and set-set cases to exact construction.
- [ ] Route only opaque call-result cases on the three observed left floors to the helper.
- [ ] Keep every other arm delegated to the existing floor panic.

### Task 3: Verify proof and representative discrimination

**Files:**
- Generated only: `target/triage/subtract-floor-after.jsonl`

**Interfaces:**
- Consumes: existing SubtractOpSugar witness and the 11 retained files.
- Produces: truthful `sat`, lying `unsat`, and live `owner=subtract 10 -> 0` testimony.

- [ ] Run focused subtract and runtime-effect witness tests.
- [ ] Replay the 11 names and classify completed versus advanced loud fronts.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Commit, rebase, push, open draft PR, attach receipts, and mark ready without merging.
