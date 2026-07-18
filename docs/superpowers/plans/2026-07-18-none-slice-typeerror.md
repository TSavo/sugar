# None Slice TypeError Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct Python's exact `TypeError` exceptional exit when a slice subscript is applied to the concrete `None` value.

**Architecture:** Put the ground-operation semantics at the `NoneValue.subscript` floor, where the receiver's Python type is already proven. Reuse the established ground exceptional-exit shape (`RaiseEffect`, `ExceptionValue`, `RaiseValue`, source locus and source hash), while leaving all other receiver floors unchanged. Add a SliceSubscriptSugar witness whose failing path cites the exceptional exit and whose continuing path gives a truthful/lying solver verdict.

**Tech Stack:** Python 3.14, pytest, Sugar Python factory, Sugar real-solver witness harness.

## Global Constraints

- Construct or panic; never add empty success.
- `None[:]` is ground and cannot mint a RuntimeEffect.
- Unrecognized ground receivers remain loud.
- The exceptional exit terminates the reduced path and carries exact source testimony.
- If a claim-mass-pinned fixture advances, re-pin its exact account in this PR.

---

### Task 1: Red discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_subscript_sugar.py`

**Interfaces:**
- Consumes: `_outcome`, `RaiseValue`, `ExceptionValue`, and `FactoryPanic`.
- Produces: exact `None[:]` exit assertions, a covered list-slice twin, and an unsupported ground-receiver twin.

- [ ] Add `None[:]` and assert a `RaiseValue` with `TypeError`, relative locus, and `ExceptionValue("TypeError")`.
- [ ] Assert `[1, 2][:]` remains an ordinary completed slice.
- [ ] Assert `3[:]` remains a loud `FactoryPanic`.
- [ ] Run the three arms and observe only the `None[:]` arm fail at `owner=subscript observed=NoneValue`.

### Task 2: Exact ground exceptional exit

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/none_value.py`

**Interfaces:**
- Consumes: `NoneValue.subscript(index, site)`.
- Produces: `Complete(RaiseValue(RaiseEffect("TypeError", ...), ExceptionValue(...)))`.

- [ ] Implement `NoneValue.subscript` with source-relative locus enforcement and source SHA-256 testimony.
- [ ] Run the discrimination arms green.
- [ ] Run the focused subscript suite green.

### Task 3: Witness and representative receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/slice_subscript_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_subscript_sugar.py`
- Modify only if proven necessary: claim-mass pin fixture.

**Interfaces:**
- Consumes: `SliceSubscriptSugar.witnesses`, `run_source_through_real_solver`, and pandas `c_parser_wrapper.py`.
- Produces: fresh truthful SAT / lying UNSAT witness and terminal conservation.

- [ ] Add a witness with a `None[:]` exceptional branch and verdict-bearing continuing branch.
- [ ] Run the witness on final rebased provenance and prove truthful SAT / lying UNSAT.
- [ ] Replay `pandas/io/parsers/c_parser_wrapper.py`; record `subscript/NoneValue` 1 to 0 and name the next loud owner or completion, with silent 0.
- [ ] Run the direct claim-mass tripwire; re-pin only if this change advances a pinned fixture.
- [ ] Commit as T Savo, push, and open a ready non-closing PR with `Part of #5133`.
