# Setitem Formal Caller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `obj[key] = value` inside a source-defined helper defer over formal operands and discharge to the actual caller's completed or named exceptional `setitem` outcome.

**Architecture:** Preserve Python source evaluation as RHS, receiver, index in `SubscriptStoreEffectSugar.desugar`. When any evaluated operand carries a formal coordinate, mint `NativeOperationExitCarrierV1` in projector order `(receiver, index, value)` with exactly aligned coordinate slots; otherwise retain the ground `receiver.setitem(index, value, site)` path. Existing `CallSiteSugar`, `SourceCallFrame`, carrier, projector, ExitSet, and assertion boundary consume the result unchanged.

**Tech Stack:** Python 3.12.13, pytest, Sugar source tree and shared ExitSet/native-operation carrier.

## Global Constraints

- Do not edit reserved carrier, projector, binder, CallSiteSugar, SymbolicValue, ExitSet, With, AttributeStore, or standalone attribution-probe files.
- Never manufacture an exception identity or completion; unresolved helper-only operations remain deferred.
- Source evaluation order is value, receiver, index; discharge order is receiver, index, value.
- Commit as `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Pin the production vertical

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_subscript_store_desugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/store_effect_sugar.py`

**Interfaces:**
- Consumes: `NativeOperationExitCarrierV1.mint(site, operator, operands, coordinates)` and the `setitem` projector.
- Produces: deferred `setitem` carrier from `SubscriptStoreEffectSugar._store`.

- [ ] Add a failing helper-only test asserting one carrier with operands and coordinates ordered receiver, index, value.
- [ ] Run that test and verify the existing `SugarNotWritten` refusal is the failure.
- [ ] Add the minimal formal-coordinate detection and carrier mint in `_store`.
- [ ] Run the helper-only test and all existing SubscriptStore laws green.

### Task 2: Prove caller outcomes and boundary typing

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_function_formal_native_operation_projection.py`

**Interfaces:**
- Consumes: ordinary source-call binder and native-operation discharge.
- Produces: positional, keyword, and default caller twins for completed and named exceptional store exits.

- [ ] Add failing source-call tests for positional, keyword, and default callers reaching the same demand coordinate.
- [ ] Add completion, immutable-receiver named halt, and wrong-boundary-type non-consumption assertions.
- [ ] Run the tests red before production wiring and green afterward.

### Task 3: Mutation and focused verification

**Files:**
- Test: both files above plus existing carrier and assertion-boundary focused suites.

- [ ] Swap index and value in the production mint, run the lying twin, and record its failure.
- [ ] Restore receiver, index, value order and rerun focused tests for every touched package.
- [ ] Verify the authenticated pandas coordinates, format, diff, exact author, push, and open an unmerged PR naming the Python assignment evaluation and setitem-discharge laws.

