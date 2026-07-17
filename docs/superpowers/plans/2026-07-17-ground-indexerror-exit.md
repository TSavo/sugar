# Ground IndexError Exceptional Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct and propagate the exact Python `IndexError` exceptional exit for concrete out-of-range sequence subscripts.

**Architecture:** The shared ground bounds-check helper constructs a source-cited `RaiseValue`. The completed-outcome sequencer recognizes that control-flow value as terminal so outer expression machinery cannot consume it as an ordinary operand.

**Tech Stack:** Python 3.14, Sugar floor/outcome protocols, pytest, Black 26.5.1.

## Global Constraints

- No RuntimeEffect constructor.
- No empty-success arm.
- Runtime-selected and unsupported index shapes remain loud.
- Use the worktree-local `.venv-lane`.

---

### Task 1: RED exceptional-exit discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_subscript_sugar.py`

**Interfaces:**
- Consumes: `SubscriptSugar` and sequence floor bounds checks
- Produces: exact `RaiseValue` and routing assertions

- [ ] Add tests for ground out-of-range construction, in-range
  discrimination, outer-expression short circuit, and `except IndexError`
  routing with a wrong-handler twin.
- [ ] Run the focused tests and confirm RED at the existing
  `owner=ListValue.subscript` panic.

### Task 2: Construct and propagate IndexError

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/ground_index_error.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/complete.py`
- Modify: concrete sequence callers as required by return typing

**Interfaces:**
- Consumes: concrete `index`, concrete `length`, and source fragment
- Produces: `Complete(RaiseValue(RaiseEffect("IndexError", ...)))`

- [ ] Replace the loud placeholder with exact source-cited construction.
- [ ] Make `Complete.and_then` propagate `RaiseValue` without evaluating the
  continuation.
- [ ] Run focused tests to GREEN and format changed Python with Black 26.5.1.

### Task 3: Witness and bounded conservation receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/subscript_sugar.py`
- Modify: focused witness tests if required

**Interfaces:**
- Consumes: the constructed exceptional-exit route
- Produces: truthful SAT and lying UNSAT witness testimony

- [ ] Retarget or add the `SubscriptSugar` witness to exercise a caught ground
  `IndexError`, preserving a refuting wrong twin.
- [ ] Run the focused witness and RuntimeEffect constructor-site census.
- [ ] Replay the two named pandas files and record exact conservation.
- [ ] Rebase current main, rerun the bounded receipts, commit as T Savo, push,
  open a non-closing `Part of #5003` draft PR, and mark it ready only after
  attaching receipts.

