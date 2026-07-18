# Raise Expression Outcome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct explicit raises whose reduced exception expression already carries exact exception or exceptional-exit evidence.

**Architecture:** Extend `RaiseSugar` at its reduced-value boundary. Dig source-backed callsites using the existing callsite floor mechanism, preserve the final opaque callsite for an exact native-exception oracle check, preserve already-raised terminals, and distribute only across fully constructed guarded outcomes.

**Tech Stack:** Python 3.14, pytest, Sugar floor algebra, real solver witness harness.

## Global Constraints

- Construct or panic; never add empty success.
- Runtime-computed exception identities remain a named `RaiseSugar` panic.
- Add no RuntimeEffect constructor.
- Trust reduced outcomes, not AST spelling or annotations.
- Witness twins are written to files and never echoed to the terminal.

---

### Task 1: Red discrimination

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_raise_expression_outcome.py`

**Interfaces:**
- Consumes: `RaiseSugar`, source-backed `CallSiteValue`, `ExceptionalExitValue`, and `GuardedValue`.
- Produces: exact good/bad twin expectations for the construction boundary.

- [x] Write tests for a helper-returned `ExceptionValue`, qualified native exception leaf, helper-raised exceptional exit, fully constructed guarded outcome, and opaque runtime-selected callable.
- [x] Run the focused file and verify the missing construction arms fail.

### Task 2: Minimal construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/raise_sugar.py`

**Interfaces:**
- Consumes: `_constructed_raise(value, ctx, source_sha256)`.
- Produces: `Complete(RaiseValue)` or the existing named `FactoryPanic`.

- [x] Dig a source-backed callsite and recurse only when it yields a more precise floor.
- [x] Preserve a final bodyless qualified callsite and require the install-source
  oracle to prove its loaded export is an exception class.
- [x] Preserve an `ExceptionalExitValue` as the terminal that occurred while evaluating the exception expression.
- [x] Distribute a guarded value only when both faces construct exact raise terminals.
- [x] Run the focused discrimination green.

### Task 3: Receipt and publish

**Files:**
- Create: `docs/ledgers/raise-expression-outcome-5145-2026-07-18.md`
- Modify only if proven necessary: claim-mass pin fixture.

**Interfaces:**
- Consumes: four named representatives and the real solver harness.
- Produces: conservation table, SAT/UNSAT witness, and PR receipt.

- [x] Replay the four named current-main representatives.
- [x] Run the direct claim-mass tripwire; re-pin only exact proven movement.
- [x] Confirm no effect-constructor site changed, so the invariant census is not applicable.
- [ ] Commit as T Savo, push, and open a non-closing draft PR with `Part of #5145`.
