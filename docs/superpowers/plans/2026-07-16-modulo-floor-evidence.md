# Modulo Floor Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one verified body-less call-result modulo panic with authenticated runtime evidence while preserving every merely unsupported floor.

**Architecture:** A dedicated effect helper owns runtime `%` testimony. `TermValue.modulo` admits only the observed `CallSiteValue(body=None)` divisor; the existing `ModuloOpSugar` remains the verdict-bearing construction owner.

**Tech Stack:** Python 3.14, pytest, Sugar Python floor values, ProofIR terms, and RuntimeEffectWitness.

## Global Constraints

- Part of #4801; never closes or fixes it.
- RuntimeEffect denotes only genuine runtime-by-nature dependence.
- A diggable or merely unsupported shape must remain FactoryPanic.
- Replay only the named pandas representative; no full-corpus sweep.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Pin the #4265 modulo discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_modulo_op.py`

**Interfaces:**
- Consumes: `TermValue`, `CallSiteValue`, `SourceFragment`, and `ModuloOpSugar.witnesses()`.
- Produces: RED coverage for the opaque runtime arm and a wrong twin that rejects a diggable body.

- [ ] Add a test for `TermValue(15) % CallSiteValue("Timedelta", body=None)` that expects an incomplete named effect with `%`, `py.modulo`, and `t.py:1:0` witness coordinates.
- [ ] Add a real `SugarBody` callsite peer and assert it raises `FactoryPanic` with `owner=modulo`.
- [ ] Retain the existing literal construction and unsupported string panic controls.
- [ ] Add a real-solver test that executes `ModuloOpSugar.witnesses()` and expects truthful SAT and lying UNSAT.
- [ ] Run the opaque test before production edits and record the existing modulo floor failure.

### Task 2: Construct authenticated modulo evidence

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/modulo_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/term_value.py`

**Interfaces:**
- Consumes: `runtime_effect_witness(operation, operand, site)`.
- Produces: `runtime_modulo(left, right, site) -> Incomplete[ModuloRuntimeEffect]`.

- [ ] Define `ModuloRuntimeEffect(RuntimeEffect)` with its own `kind`.
- [ ] Build the full `%` term and authenticate it as `py.modulo`.
- [ ] Dispatch only `CallSiteValue(body=None)` through the helper.
- [ ] Run the focused modulo and RuntimeEffectWitness suites.

### Task 3: Measure conservation and publish

**Files:**
- No production files beyond Tasks 1 and 2.

**Interfaces:**
- Consumes: the one retained pandas file and focused test suite.
- Produces: `owner=modulo 1 -> 0`, named destination mass, `silent=0`, and a ready non-closing PR.

- [ ] Replay `pandas/tests/scalar/timedelta/test_arithmetic.py` and record its actual terminal or completion.
- [ ] Report predicted and observed bucket movement: mandatory panic `-1`, typed effect `+1`, suppressed descendants `0`, silent `0`.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Rebase on current `origin/main`, run the exact focused receipt, and commit with the required author.
- [ ] Push `modulo-floor-evidence`, open a draft PR with `Part of #4801`, post receipts, then mark ready without merging.
