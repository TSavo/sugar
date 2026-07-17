# Power Floor Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 12 power-floor corpus panics with exact native evidence or a witnessed named runtime effect.

**Architecture:** Extend the existing `TermValue.power` integer-warrant path for `len(...)`. Give `CallSiteValue.power` its own dig-first dispatch and a `PowerRuntimeEffect` fallback instead of reusing the generic symbolic binary fallback.

**Tech Stack:** Python 3.14, pytest, Sugar ProofIR terms, real Sugar solver witness harness.

## Global Constraints

- Never translate a floor panic into unwarranted success.
- Runtime-dependent `__pow__` dispatch stays a loud named effect.
- Use only the 12 named representative files; do not run a full corpus sweep.
- Do not gate on the pre-existing pyright/type-ratchet wall.

---

### Task 1: Pin the two power boundaries red

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_power_op_sugar.py`

**Interfaces:**
- Consumes: `reduce_value`, `OpaqueOpCallsite`, `CallSiteValue`.
- Produces: assertions for native `**` construction and `PowerRuntimeEffect` testimony.

- [ ] Add a test requiring `10 ** len(xs)` to equal `SymbolicValue(ctor("**", [num(10), call_len]))`.
- [ ] Add a test requiring `f(x) ** 2` to return `Incomplete(PowerRuntimeEffect)` with operation `py.power` and both operands in its witnessed term.
- [ ] Run both tests and retain the two current `FactoryPanic` failures as the RED receipt.

### Task 2: Construct the exact/effect split

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/power_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/term_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/call_site_value.py`

**Interfaces:**
- Consumes: the existing `runtime_effect_witness`, callsite dig, and native `**` coordinate.
- Produces: `PowerRuntimeEffect` and an integer-warranted symbolic power term.

- [ ] Define and export `PowerRuntimeEffect(RuntimeEffect)`.
- [ ] Route only `OpaqueOpCallsite(callee="len")` through the concrete-base native-coordinate arm.
- [ ] Add `CallSiteValue.power`: dig and redispatch when possible; otherwise return a witnessed `PowerRuntimeEffect` whose operand is `ctor("**", [base, exponent])`.
- [ ] Run focused tests and require both new tests green without changing any existing loud fallback.

### Task 3: Verify proof and corpus discrimination

**Files:**
- Generated only: `target/triage/power-floor-after.jsonl`

**Interfaces:**
- Consumes: existing PowerOpSugar witnesses and the 12 named corpus representatives.
- Produces: truthful `sat`, lying `unsat`, and `owner=power 12 -> 0` telemetry.

- [ ] Run the focused power, runtime-effect witness, and wrong-twin solver tests.
- [ ] Replay the 12 named representatives and classify complete versus advanced loud fronts.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Rebase on current main, push, open draft PR, then mark ready after receipts are attached.
