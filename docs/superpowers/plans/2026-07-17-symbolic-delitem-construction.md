# Symbolic Delitem Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct symbolic and concrete mapping deletion post-states so the
live NumPy `delitem` terminal advances honestly.

**Architecture:** Extend the receiver-owned delitem floor, mirroring the
existing setitem and callsite coordinate patterns. Concrete mappings fold;
symbolic mappings retain an explicit `py.delitem` coordinate; unsupported
ground receivers still panic.

**Tech Stack:** Python 3.14, pytest, ProofIR terms, black 26.5.1.

## Global Constraints

- Part of #4847; never closes/fixes.
- No RuntimeEffect for unimplemented machinery.
- Effect arms only for genuine runtime dependence through RuntimeOperand.
- No full-corpus sweep.
- Author T Savo `<evilgenius@nefariousplan.com>`.
- Do not merge.

---

### Task 1: Pin receiver-owned deletion

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_delete_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/symbolic_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/dict_value.py`

**Interfaces:**
- Consumes: `FloorValue.delitem(index, site)`.
- Produces: `Complete(CallSiteValue(py.delitem(...)))` for symbolic receivers
  and `Complete(DictValue(...))` for ground mappings.

- [ ] Add tests for symbolic rebind, concrete dict removal, and a
  non-container `FactoryPanic` bad twin.
- [ ] Run the focused tests and record the expected `owner=delitem` red.
- [ ] Implement the minimal receiver-owned floors.
- [ ] Re-run the focused tests green.

### Task 2: Add verdict-bearing evidence

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/subscript_delete_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_delete_sugar.py`

**Interfaces:**
- Consumes: `SubscriptDeleteSugar.witnesses()`.
- Produces: a named concrete-dict truthful/lying witness pair.

- [ ] Add the dict deletion witness and a focused real-solver test.
- [ ] Run truthful and lying arms; require `sat` and `unsat`.
- [ ] Run focused delete regressions and the effect-constructor invariant if an
  effect construction site changes.

### Task 3: Receipt and publish

**Files:**
- Measure:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`

**Interfaces:**
- Consumes: installed `numpy/f2py/symbolic.py`.
- Produces: named-terminal conservation for #4847.

- [ ] Replay the bounded representative and record where mass moves.
- [ ] Run black 26.5.1 and `git diff --check`.
- [ ] Rebase on current `origin/main`, repeat focused receipts, commit and push.
- [ ] Open a non-closing draft PR with `Part of #4847`, post receipts, then
  mark ready without merging.
