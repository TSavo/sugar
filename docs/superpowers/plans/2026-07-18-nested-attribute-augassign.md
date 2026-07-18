# Nested Attribute AugAssign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Construct name-rooted nested-attribute AugAssign through the factory and floor, retiring the verified SciPy `python.factory` panic without overlapping #5258.

**Architecture:** Add one structural recognition coordinate, expose it through `SourceFragment`, and register a dedicated statement Sugar. The Sugar factory-builds the ordinary AugAssign binop child and rebinds the exact dotted target after floor reduction.

**Tech Stack:** Python 3.12.3, pytest, Sugar factory/recognition/floor APIs.

## Global Constraints

- Do not modify tuple-unpack recognition or #5258's files.
- Do not add an inline AST classifier to a Sugar.
- Do not add a RuntimeEffect constructor, suppression, allowlist, or empty-success arm.
- Unsupported shapes remain `FactoryPanic`.
- Run the full eight-axis Python sole-construction floors gate.

---

### Task 1: Pin the structural partition with a failing test

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_nested_attribute_augassign_sugar.py`

**Interfaces:**
- Consumes: `default_catalog()`, `build_node()`, and the existing exact SciPy source node.
- Produces: a red owner-selection test and loud bad-shape discrimination.

- [ ] Add a test asserting the exact SciPy node selects `NestedAttributeAugAssignSugar`.
- [ ] Add a concrete reduction test for a nested dotted division.
- [ ] Add call-rooted and subscript-rooted bad twins that require `FactoryPanic`.
- [ ] Run the focused test and verify it fails because the new owner is absent.

### Task 2: Add factory recognition and construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/recognition/binding_shapes.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_fragment.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/nested_attribute_aug_assign_sugar.py`

**Interfaces:**
- Produces: `BindingShapeRecognition.augassign_dotted_path(site)`,
  `SourceFragment.aug_assign_target_dotted_attribute_path()`, and
  `NestedAttributeAugAssignSugar`.

- [ ] Recognize only pure name-rooted nested dotted AugAssign targets.
- [ ] Expose the recognition through `SourceFragment`.
- [ ] Implement `owns()` solely from the recognized coordinate.
- [ ] Factory-build `site.aug_assign_binop()` with `ctx.build_body`.
- [ ] Reduce through the child floor and return `ScopeRebind(".".join(path), updated)`.
- [ ] Register truthful and lying witnesses with `_call_pair`.
- [ ] Run the focused test and verify green.

### Task 3: Verify the representative and architecture floors

**Files:**
- No production changes.

**Interfaces:**
- Consumes: the exact SciPy source and repository floor instruments.
- Produces: the PR receipt.

- [ ] Replay `_basinhopping.py:241:12` and verify the selected owner is `NestedAttributeAugAssignSugar`.
- [ ] Run the focused witness instrument and verify truthful SAT / lying UNSAT.
- [ ] Run the full Python sole-construction floors gate and verify all eight axes are green.
- [ ] Confirm the diff does not touch tuple-unpack files and contains no effect constructor.
- [ ] Commit as T Savo, push, and open a non-closing PR with `Part of #5265`.
