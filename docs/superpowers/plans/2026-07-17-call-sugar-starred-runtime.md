# CallSugar Runtime Starred-Positional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct an honest typed runtime outcome for symbolic starred positional binding while keeping every unbuilt or ground-invalid shape loud.

**Architecture:** The bound-function positional binder returns either an exact expanded tuple or an `Incomplete` carrying a sealed runtime effect. Its two callers propagate the incomplete outcome before signature binding. Syntax recognition and coordinate-only calls remain unchanged.

**Tech Stack:** Python 3.14, pytest, Black 26.5.1, Sugar Python lift kit.

## Global Constraints

- Runtime effects require a genuine runtime operand through `runtime_effect_evidence`.
- Ground values, mappings, and unbuilt machinery must remain `FactoryPanic`.
- No verifier changes and no full-corpus census.
- Receipt is bounded to the two named representatives.

---

### Task 1: Red discrimination and witness

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_function_callable_starred_positional.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_sugar.py`

**Interfaces:**
- Consumes: `_expand_function_positional_args(arg_values, site=...)`
- Produces: tests for a named effect, static controls, ground wrong twins, and a `CallSugar` typed-red witness

- [ ] Add a test requiring a symbolic star to return `Incomplete(StarredPositionalRuntimeEffect)`.
- [ ] Preserve the tuple/list expansion assertions and scalar/mapping panic assertions.
- [ ] Add a typed-red `CallSugar` witness whose wrong reason does not match.
- [ ] Run the focused tests and confirm the missing effect class/result fails red.

### Task 2: Runtime effect construction

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/starred_positional_runtime_effect.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/keyword_call_sugar.py`

**Interfaces:**
- Produces: `StarredPositionalRuntimeEffect(RuntimeEffect)`
- Produces: `_expand_function_positional_args(...) -> tuple | Incomplete`

- [ ] Define and export the named runtime effect.
- [ ] Construct it only for `SymbolicValue` via `runtime_effect_evidence`.
- [ ] Propagate `Incomplete` from both bound-function call paths.
- [ ] Leave `CallSiteValue`, mappings, scalars, and unknown floors on the existing panic arm.
- [ ] Run the focused discrimination and witness tests green.

### Task 3: Bounded receipt and publication

**Files:**
- Verify: `numpy/lib/_format_impl.py`
- Verify: `numpy/_core/tests/test_einsum.py`

**Interfaces:**
- Produces: conservation counts for issue and PR receipts

- [ ] Run the RuntimeEffect constructor-site invariant and confirm zero failures.
- [ ] Replay both named representatives with a source-matched binary.
- [ ] Record completed, advanced-to-named, typed-effect, and silent counts.
- [ ] Format with Black 26.5.1 and run the focused test slice.
- [ ] Rebase current main, repeat the receipt, commit as T Savo, push, open a draft non-closing PR, post the receipt, and mark it ready.

