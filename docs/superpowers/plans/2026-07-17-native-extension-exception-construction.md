# Native Extension Exception Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact native-extension exception class evidence so statically named exceptions reach `RaiseSugar` as `ExceptionValue`.

**Architecture:** Refine the existing install-source native-symbol resolver at its ownership boundary. Resolve the exact loaded export, classify only actual `BaseException` subclasses as `ExceptionClassValue`, and preserve the existing native-callable lane for every other export.

**Tech Stack:** Python 3.14, pytest, pinned Black 26.5.1, Sugar Python lift kit.

## Global Constraints

- Construct-or-panic; never add empty success.
- No runtime effect is added or touched.
- A runtime-selected exception class remains a loud `RaiseSugar` panic.
- Use only the worktree-local `.venv-lane`.

---

### Task 1: Native exception discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_imported_exception_class_floor.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: `resolve_install_source_value(import_target, ctx)`
- Produces: `ExceptionClassValue` for a proved native exception export

- [ ] **Step 1: Write the failing discrimination tests**

Add tests proving `_csv.Error` resolves as `ExceptionClassValue`, raises as an
exact `ExceptionValue`, and `_csv.Dialect` does not acquire exception
authority.

- [ ] **Step 2: Run the tests and verify RED**

Run:
`black --check implementations/python/sugar-lift-py-tests/tests/test_imported_exception_class_floor.py && pytest -q implementations/python/sugar-lift-py-tests/tests/test_imported_exception_class_floor.py`

Expected: the native exception assertions fail because `_csv.Error` is still a
`NativeCallableValue`.

- [ ] **Step 3: Implement the minimal resolver refinement**

Follow the existing static native re-export route. Import the resolved module,
read the exact export, and return `ExceptionClassValue` only when it is a class
whose real ancestry includes `BaseException`; otherwise return the existing
`NativeCallableValue`.

- [ ] **Step 4: Run focused GREEN**

Run the command from Step 2.

Expected: all imported-exception tests pass.

### Task 2: Verdict witness and bounded receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/raise_sugar.py`

**Interfaces:**
- Consumes: the native exception classification from Task 1
- Produces: truthful/lying `RaiseSugar` witness coverage of that route

- [ ] **Step 1: Enroll the native exception path in the witness**

Use `from _csv import Error` and `raise Error(...)` in the existing
`RaiseSugar` truthful/lying witness.

- [ ] **Step 2: Verify focused tests and witness**

Run the imported-exception tests, the focused RaiseSugar witness selector, and
the truthful/lying witness verification.

- [ ] **Step 3: Replay the two named representatives**

Replay `pandas/core/resample.py` and `pandas/core/groupby/groupby.py` with the
worktree-local environment. Record resample `RaiseSugar 1 -> 0`, groupby
remaining loud `RaiseSugar 1 -> 1`, and `silent=0`.

- [ ] **Step 4: Run formatting and invariant checks**

Run pinned Black 26.5.1 on changed Python files and the RuntimeEffect
constructor-site invariant. No constructor site should change and
`CONSTRUCTOR_SITES FAILED` must remain zero.

- [ ] **Step 5: Commit and publish**

Commit as T Savo, push the branch, open a non-closing draft PR with
`Part of #4988`, attach receipts, then mark it ready.

