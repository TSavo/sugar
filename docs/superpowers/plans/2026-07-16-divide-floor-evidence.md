# Divide Floor Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one proven native-callable division floor with authenticated runtime evidence without weakening any unsupported division refusal.

**Architecture:** A dedicated effect constructor owns runtime `/` testimony. `NativeCallableValue` admits only the observed opaque-call-result peer; `DivideOpSugar` remains the verdict-bearing callsite.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift floors and runtime-effect witnesses.

## Global Constraints

- Part of #4781; never closes or fixes it.
- Never translate a missing floor or runtime-dependent outcome into success.
- Replay only the named pandas representative; do not run a full corpus sweep.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Pin the divide boundary and discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_divide_op.py`

**Interfaces:**
- Consumes: `NativeCallableValue`, `CallSiteValue`, `SourceFragment`, and the existing real-solver witness harness.
- Produces: a RED test for the missing runtime boundary, a loud unsupported sibling, and SAT/UNSAT proof discrimination.

- [ ] Add a test constructing `NativeCallableValue("pandas.NaT", ...) / CallSiteValue("Timedelta", ...)` at a real source fragment and assert a named witnessed incomplete result.
- [ ] Add sibling assertions that `NativeCallableValue / TermValue` and a
  callsite with a diggable body still panic with `owner=divide`; neither is
  admissible as #4265 runtime-dependence evidence.
- [ ] Add a real-solver test for the existing truthful `10 / 2 == 5` and lying `10 / 2 == 4` claims.
- [ ] Run the focused new tests and record the expected missing-effect/floor failure before production edits.

### Task 2: Construct authenticated divide runtime evidence

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/divide_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/native_callable_value.py`

**Interfaces:**
- Consumes: `runtime_effect_witness(operation, operand, site)`.
- Produces: `runtime_divide(left, right, site) -> Incomplete[DivideRuntimeEffect]`.

- [ ] Define `DivideRuntimeEffect(RuntimeEffect)` and return its own kind.
- [ ] Build `ctor("/", [left.to_term(...), right.to_term(...)])` and authenticate it as `py.divide`.
- [ ] Dispatch only the observed `NativeCallableValue / CallSiteValue(body=None)` pair through the helper.
- [ ] Run the focused divide and runtime-effect witness suites.

### Task 3: Measure and publish

**Files:**
- No production files beyond Tasks 1 and 2.

**Interfaces:**
- Consumes: the one retained pandas file and the focused test suite.
- Produces: `owner=divide 1 -> 0`, the truthful/lying verdict receipt, and an open ready PR.

- [ ] Replay `pandas/tests/scalar/timedelta/test_arithmetic.py` and record its actual terminal.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Rebase on current `origin/main`, rerun focused verification, and commit with the required author.
- [ ] Push `divide-floor-evidence`, open a draft PR with `Part of #4781`, post receipts, then mark ready without merging.
