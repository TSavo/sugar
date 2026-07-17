# Inherited BytesIO Constructor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the exact one-seed inherited `io.BytesIO` constructor used by NumPy.

**Architecture:** Add a closed matcher before generic imported-base source digging. It reuses `ConstructorStrategy` and the existing `__bytesio_buffer__` structural coordinate; all nonmatching cases retain the current panic.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift factory.

## Global Constraints

- No `RuntimeEffect` constructor site.
- No empty-success arm.
- Unsupported, shadowed, dynamic, or wrong-arity shapes stay loud.
- Use focused tests and one named representative; no corpus sweep.

---

### Task 1: Exact inherited BytesIO construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`

**Interfaces:**
- Consumes: `ImportAliasValue.import_target`, `ConstructorStrategy`, `_class_fields`.
- Produces: a closed inherited-BytesIO `ConstructorStrategy` with `__bytesio_buffer__`.

- [ ] **Step 1: Write the failing tests**

Add a positive test for one positional seed and negative tests for zero
arguments, two arguments, and a shadowed `BytesIO` binding. Add a
`ConstructorCallSugar` witness pair whose truthful arm asserts a subclass
method result and whose lying arm asserts the wrong result.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q -o addopts='' \
  implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py \
  -k 'inherited_bytesio'
```

Expected: the positive test fails with the existing
`statically resolved inherited constructor` `FactoryPanic`.

- [ ] **Step 3: Implement the minimal closed matcher**

Match one source base name whose live temporal binding is exactly
`io.BytesIO` or `_io.BytesIO`, require exactly one positional call argument,
and return `ConstructorStrategy(fields=(("__bytesio_buffer__", argument), ...))`.
Return `None` for every nonmatch so the existing loud path remains authoritative.

- [ ] **Step 4: Verify GREEN and discrimination**

Run the focused inherited-BytesIO tests and the truthful/lying solver witness.
Both boundary negatives must remain `FactoryPanic`.

- [ ] **Step 5: Replay and publish**

Replay only `numpy/lib/tests/test_format.py`, report conservation and `silent=0`,
rebase on final `origin/main`, rerun the witness, format, commit, push, and open
a non-closing PR with `Part of #5082`.
