# Constructor Call Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct proof-bearing generated/default constructor fields while keeping inherited, effectful, and impossible constructor calls loudly witnessed.

**Architecture:** Extend the existing `ConstructorStrategy` path rather than add another Sugar owner. Exact generated constructors compile annotations into the same field/parameter strategy used by assignment-only `__init__`; a separate runtime strategy reduces real arguments and emits authenticated named effects without producing an object.

**Tech Stack:** Python 3.14, pytest, Black 26.5.1, existing Sugar witness harness and corpus child harness.

## Global Constraints

- Part of #4727; never closes/fixes #4727 from the PR body.
- Never weaken or catch a factory panic to manufacture success.
- Runtime-dependent construction remains a loud named effect.
- Every runtime effect carries a genuine source-fragment witness.
- Do not gate on or chase the pre-existing pyright/type-ratchet wall.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Pin generated, defaulted, and runtime constructor behavior

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`

**Interfaces:**
- Consumes: `ConstructorCallSugar`, `ObjectValue`, `Incomplete`, and the real solver witness harness.
- Produces: red tests for generated fields, positional defaults, named runtime effects, and witnessed arity errors.

- [ ] **Step 1: Write failing tests**

Add tests that reduce `@dataclass class Box: x: int`, `class Pair(NamedTuple): left: int; right: int`, and `class Box: def __init__(self, x, y=2): self.x=x; self.y=y`. Add inherited/effectful constructor tests asserting `ConstructorRuntimeEffect`, plus an impossible-arity test asserting `TypeErrorRuntimeEffect`. Add real-solver truthful/lying pairs for each constructed form.

- [ ] **Step 2: Verify red**

Run:
` .venv/bin/pytest -q implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py `

Expected: generated/default cases panic at `ConstructorCallSugar`; the named effect type is absent.

### Task 2: Construct exact generated/default strategies

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_strategy.py`

**Interfaces:**
- Consumes: `SourceFragment.class_decorators`, `class_base_names`, `annassign_target_id`, `function_defaults`, and `function_positional_arity`.
- Produces: `ConstructorStrategy` instances whose parameters, arguments, and field bodies have equal length and preserve source defaults.

- [ ] **Step 1: Add exact generated-field recognition**

Recognize only bare `@dataclass` or exact `NamedTuple` bases. Require annotation-only bodies and exact positional arity, then build each annotated target as both a parameter and field body.

- [ ] **Step 2: Add explicit positional-default binding**

Require a simple positional signature. Accept calls inside `function_positional_arity()`, append the needed trailing `function_defaults()` bodies, and retain the existing assignment-only body construction.

- [ ] **Step 3: Verify constructed cases green**

Run the three generated/default reduction tests and their truthful/lying real-solver pairs. Expected: truthful `sat`; lying `unsat`.

### Task 3: Preserve runtime and impossible boundaries

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/constructor_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_strategy.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`

**Interfaces:**
- Consumes: reduced constructor argument floors and the genuine call-site `SourceFragment`.
- Produces: `ConstructorRuntimeEffect` for inherited/effectful construction and `TypeErrorRuntimeEffect` for proven arity failure, both witnessed by `python:constructor_call(class, args...)`.

- [ ] **Step 1: Add the named runtime effect and strategy**

Define `ConstructorRuntimeEffect(RuntimeEffect)` and a strategy that reduces arguments left-to-right, builds the constructor-call operand term, and returns `Incomplete` with a mandatory `runtime_effect_witness`.

- [ ] **Step 2: Route only unproved shapes to typed red**

Use the runtime strategy for inheritance/dynamic body semantics. Use its arity-error arm only when the static signature proves the supplied positional count impossible. Do not return `ObjectValue` from either arm.

- [ ] **Step 3: Verify effect discriminations green**

Run the inherited/effectful/arity tests plus `test_runtime_effect_witness.py` and `test_runtime_effect_witness_sweep.py`. Expected: all pass and no effect subclass is instantiable without a witness.

### Task 4: Corpus telemetry and publication

**Files:**
- Generated only: `target/triage/constructor-call-after.jsonl` (never commit)

**Interfaces:**
- Consumes: the 17 current-main `ConstructorCallSugar` representative files.
- Produces: per-file terminal testimony and a zero remaining-owner count.

- [ ] **Step 1: Run formatting and focused regression tests**

Run Black 26.5.1 on changed Python files and the focused constructor/runtime/witness tests. Do not run the pyright ratchet as a gate.

- [ ] **Step 2: Replay isolated corpus children**

Run each representative in a fresh process, normalize `FactoryGapInfo.blame` only for telemetry serialization, and require `remaining owner=ConstructorCallSugar` to equal zero. Report completed files separately from files advancing to another loud owner.

- [ ] **Step 3: Commit, push, and open draft PR**

Commit with `T Savo <evilgenius@nefariousplan.com>`, push `constructor-call-evidence`, and open a non-closing draft PR with body `Part of #4727` and red/green receipts.

- [ ] **Step 4: Rebase and mark ready after telemetry**

Fetch and rebase onto current `origin/main`, rerun focused verification, force-with-lease push if required, then mark the mergeable PR ready. Do not merge.
