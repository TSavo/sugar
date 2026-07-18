# Nested-Tuple For/Else Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the two current-main nested-tuple `for/else` statement shapes through `ForElseSugar`.

**Architecture:** Normalize simple, flat-tuple, and nested-tuple loop targets into projection-path leaves using `BindingShapeRecognition`. `ForElseSugar` consumes those recognized leaves, factory-builds its three child bodies, and reuses its existing no-break/else reduction.

**Tech Stack:** CPython 3.12.3, pytest, Sugar factory/SugarBody, pinned Black 26.5.1.

## Global Constraints

- Strictly CPython `3.12.3`.
- No inline AST classifier or vendor-name matcher in the Sugar.
- Unsupported target shapes remain `FactoryPanic`.
- No RuntimeEffect-as-gap, empty success, baseline, allowlist, or suppression.
- Author: `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Red discrimination

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_nested_tuple_for_else_sugar.py`

**Interfaces:**
- Consumes: `default_catalog().candidates_for(SugarRole.STATEMENT, site)`.
- Produces: failing ownership and reduction tests for nested target paths.

- [ ] Write a test asserting `for i, (left, right) in rows: ... else: ...` selects only `ForElseSugar`.
- [ ] Write bad-twin tests asserting starred or non-name target leaves have no candidate and raise `FactoryPanic`.
- [ ] Run the focused test and confirm it fails because current candidates are empty.

### Task 2: Normalize and construct target paths

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/for_else_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_nested_tuple_for_else_sugar.py`

**Interfaces:**
- Consumes: `site.for_target_name()`, `site.for_flat_tuple_target_names()`, and `site.for_nested_tuple_target_paths()`.
- Produces: normalized `targets: tuple[tuple[tuple[int, ...], str], ...]`.

- [ ] Change `owns()` to accept nested recognized paths without inspecting AST nodes.
- [ ] Change `new()` to normalize all admitted target forms and retain `ctx.build_body` for iterable/body/else children.
- [ ] Bind each leaf by folding its projection path over the constructed iteration element.
- [ ] Run focused ownership/reduction tests and confirm green.

### Task 3: Verdict witness and regressions

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/for_else_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_nested_tuple_for_else_sugar.py`

**Interfaces:**
- Consumes: `_call_pair`.
- Produces: `nested_tuple_for_else_return` truthful/lying witness.

- [ ] Add a nonempty nested-tuple `for/else` witness whose truthful assertion is SAT and lying assertion is UNSAT.
- [ ] Run existing ForSugar, TupleForSugar, NestedTupleForSugar, and ForElseSugar suites unchanged.
- [ ] Replay both SQLAlchemy nodes and record `python.factory 2 -> 0`.

### Task 4: Verify and publish

**Files:**
- Modify only formatting required by Black 26.5.1.

**Interfaces:**
- Consumes: private release binary stamped to final branch HEAD.
- Produces: issue/PR receipt for #5287.

- [ ] Run Black 26.5.1 check and `git diff --check`.
- [ ] Run the truthful/lying witness with the private commit-stamped binary.
- [ ] Run all eight sole-construction floor axes and planted-violation tests.
- [ ] Commit as T Savo, rebase current main, rerun final focused receipts, push, and open a non-closing PR with `Part of #5287`.
