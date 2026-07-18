# Qualified Vendor Isinstance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact Python type coordinates for authenticated qualified
stdlib and vendor class references used as `isinstance` type operands.

**Architecture:** `AttributeSugar` delegates qualified-class authentication to
the imported-module floor. The floor returns the existing `ImportAliasValue`
coordinate only for a concrete class object; `IsinstanceCallSugar` and
`FloorValue.python_isinstance` remain unchanged.

**Tech Stack:** Python 3, pytest, Sugar Python lift factory, Z3 witness harness.

## Global Constraints

- Construct qualified class identity; never relabel missing machinery as a
  RuntimeEffect.
- Unknown local type names remain loud.
- Add no empty-success branch.
- Use pinned Black 26.5.1 and a private worktree venv.

---

### Task 1: Red discrimination

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_isinstance_arg_dispatch.py`

**Interfaces:**
- Consumes: `reduce_value`, `ImportAliasValue`, and `IsinstanceCallSugar`.
- Produces: exact formula assertions for qualified classes and a loud bad twin.

- [ ] Add parameterized red cases for `datetime.datetime`,
  `decimal.Decimal`, and `collections.OrderedDict`.
- [ ] Assert each result is
  `adt.is_python_type(x, python:type("<qualified-name>"))`.
- [ ] Add an audit test proving an unbound local type name still raises
  `FactoryPanic`.
- [ ] Run both arms and confirm the class cases fail because they currently
  become `CallResultTypeRuntimeEffect`, while the bad twin passes.

### Task 2: Qualified class construction

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/import_alias_value.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/attribute_sugar.py`

**Interfaces:**
- Produces:
  `ImportAliasValue.qualified_class_attribute(name: str) -> ImportAliasValue | None`.
- Consumes: the source-stated module import coordinate.

- [ ] Resolve the exact module and attribute.
- [ ] Return a qualified `ImportAliasValue` only when `inspect.isclass` proves
  the object is a class.
- [ ] Route `AttributeSugar` through the recognizer before generic callsite
  construction.
- [ ] Run the discrimination and focused existing isinstance/attribute tests.

### Task 3: Verdict witness and datetime re-shot

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/isinstance_call_sugar.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_isinstance_arg_dispatch.py`

**Interfaces:**
- Produces: `isinstance_qualified_concrete_class`, truthful SAT and lying UNSAT.

- [ ] Add a witness using `datetime.datetime`.
- [ ] Run the witness through the real solver with a freshly built,
  provenance-matched release binary.
- [ ] Replay the real checked-in datetime source and record completed versus
  distinct loud owner, assertion accounting, and `silent=0`.
- [ ] Rebase, rerun the focused receipts, format with Black 26.5.1, commit as
  T Savo, push, and open a ready non-closing PR containing `Part of #5108`.
