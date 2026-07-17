# Contextmanager Yielded Value Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the exact entered value of the two authenticated
`@contextmanager` generators from their reduced yield testimony.

**Architecture:** The existing source recognizer authorizes a
contextmanager-only `SequentialDigBody` mode. That mode extracts the single
yielded term from an existing `GeneratorYieldRuntimeEffect` witness; generic or
mixed outcomes retain the existing loud panic.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Global Constraints

- Construct from reduced semantic outcomes, never pandas or NumPy AST patterns.
- No new RuntimeEffect constructor and no empty-success arm.
- Generic, mixed, unrecognized, and opaque shapes remain loud.
- Use only the worktree-local `.venv-lane`.
- Receipt is bounded named representatives; no full-corpus sweep.

---

### Task 1: Pin contextmanager-only reduced-yield projection

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_install_source_body_dig.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: `Incomplete.effect.witness.operation`.
- Produces: `SequentialDigBody(..., contextmanager_yield=True)`.

- [ ] Add a failing test whose reduced contribution is exactly one
  `GeneratorYieldRuntimeEffect` and whose expected result is the witnessed
  yielded term.
- [ ] Add the bad twin without `contextmanager_yield=True`; assert
  `FactoryPanic`.
- [ ] Run the exact tests and record the expected red panic.
- [ ] Add the minimal contextmanager-only extractor.
- [ ] Run the exact tests green.

### Task 2: Authorize installed and local contextmanager bodies

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/statement_function_def_sugar.py`
- Modify: focused tests beside the corresponding source recognizers.

**Interfaces:**
- Consumes: the existing closed contextmanager source recognizer.
- Produces: contextmanager-mode `SequentialDigBody` only when recognition
  succeeds.

- [ ] Add red tests for installed and executable local contextmanagers.
- [ ] Add multiple-yield and exit-overriding bad twins.
- [ ] Reuse one source-recognition helper for both construction paths.
- [ ] Run the focused tests green.

### Task 3: Witness and bounded receipt

**Files:**
- Modify the narrowest existing witness test or contextmanager sugar witness.

**Interfaces:**
- Produces: truthful SAT and lying UNSAT contextmanager entered-value pair.

- [ ] Add and run the verdict-bearing witness.
- [ ] Run the RuntimeEffect constructor-site census.
- [ ] Replay `numpy/lib/tests/test_io.py` and
  `pandas/tests/libs/test_hashtable.py`.
- [ ] Record conservation: `SequentialDigBody 2 -> 0`, completed versus
  advanced-to-distinct-loud, silent `0`.
- [ ] Run Black 26.5.1 on changed Python files.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>`, push, open a
  non-closing draft PR with `Part of #5036`, attach receipts, then mark ready.
