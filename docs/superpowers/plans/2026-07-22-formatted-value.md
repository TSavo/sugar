# FormattedValue Reference Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drain well-formed `FormattedValue` direct gaps by projecting the exact Python-reference `python:fstring_value(value, conversion, format_spec)` coordinate.

**Architecture:** `FormattedValue` validates its backend conversion slot and constructs a sugar carrying its value, typed conversion, and optional nested `JoinedStrSugar`. Desugaring projects the existing ProofIR constructor with explicit `None` terms and a nested `python:fstring` format specification; malformed slots remain typed loud failures.

**Tech Stack:** Python 3, sugar source tree, sugar-lift ProofIR terms, pytest, pandas construction census.

## Global Constraints

- Mirror `sugar_lift_python_source.lifter.fstring_value()` exactly: value, conversion, format spec.
- Do not emit `py.format` or a conversion intermediate.
- No vendor or name dispatch.
- Preserve child gaps exactly and classify malformed backend slots loudly.
- Python locally; Rust round-trip runs on battleaxe.
- Do not merge the non-draft PR.

---

### Task 1: Pin the five typed twins

**Files:**
- Modify: `implementations/python/sugar-source-tree/tests/test_fstring_sugar.py`

**Interfaces:**
- Consumes: `FormattedValue.sugar()` and ProofIR term constructors.
- Produces: tests for ordered operands, conversion discrimination, explicit absence, swapped operands, and malformed operands.

- [ ] **Step 1: Extend the red tests** to assert `python:fstring_value(value, conversion, format_spec)` and decoder failures for swapped or malformed terms.
- [ ] **Step 2: Run the focused test file** with the repository `PYTHONPATH`; expect the well-formed modifier cases to fail at `FormattedValue.sugar` before implementation.

### Task 2: Implement the exact reference projection

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/fstring_sugar.py`

**Interfaces:**
- Consumes: value sugar, conversion integer, optional `JoinedStr` sugar.
- Produces: `FormattedValueSugar(value, conversion, format_spec, site)` and the ordered `python:fstring_value` term.

- [ ] **Step 1: Validate conversion** as exactly `-1`, `ord("a")`, `ord("r")`, or `ord("s")`; raise `BackendDefect` otherwise.
- [ ] **Step 2: Carry all three operands** into `FormattedValueSugar`, using the optional child sugar without elision.
- [ ] **Step 3: Project the reference term** with explicit `none_const()` for absent operands and `python:fstring` for the nested spec.
- [ ] **Step 4: Run the focused tests** and require all five twins green.

### Task 3: Measure and publish

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/scripts/measure_formatted_value_frontier.py`

**Interfaces:**
- Consumes: installed pandas sources and normal function construction.
- Produces: before/after direct-gap and blocked-descendant counts.

- [ ] **Step 1: Run the family counter** before and after the arm and record the direct-gap delta.
- [ ] **Step 2: Run focused Python tree tests** and the existing Python-reference f-string tests.
- [ ] **Step 3: Run Python-to-Rust round-trip on battleaxe** and verify all operands retain reference order.
- [ ] **Step 4: Rebase onto `origin/main`, commit as T Savo, push, and open a non-draft PR** without merging it.
