# Witness Owner Classifier Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every #4397 witness registry owner equal the owner selected by live Python classifier construction, while keeping genuinely unowned shapes loud.

**Architecture:** Use the existing lift audit as the authority for live dispatch. Repair malformed witnesses so they exercise the claim that registers them; route real nested annotation, alias, and slice sites through ordinary factory construction; remove the dead `NotOpSugar` claim and move its `not` discrimination to `UnaryOpSugar`. Add one invariant that derives registry owners from catalog claims and compares them with live lift testimony, plus a planted no-owner gap that must still panic.

**Tech Stack:** Python 3.14, pytest, Sugar Python factory/catalog, lift RPC audit testimony.

## Global Constraints

- Do not weaken any factory panic, verifier refusal, or witness verdict.
- Do not invent audit-only dispatch.
- Do not rewrite expected owners to observed owners without reconciling the claim and source shape.
- Object-equality witnesses are already correct and remain unchanged.
- Use focused Python tests only; no composed mint, broad gate, or battleaxe build.

---

### Task 1: Pin registry-to-live-dispatch equality

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_sugar_witness_instruments.py`

**Interfaces:**
- Consumes: `DEFAULT_SUGAR_WITNESS_SEEDS`, `_stage_cli_project`, `run_lift_rpc`, `WitnessPipelineResult.selected_sugars`.
- Produces: a focused parametrized invariant for the eight #4397 witness families and a planted unowned-shape panic.

- [ ] Add a parametrized test that stages each named truthful witness, runs only the Python lift RPC, and asserts its catalog registry owner occurs in live selected-sugar testimony.
- [ ] Run the new test and preserve the eight-owner red receipt.
- [ ] Add a planted AST shape with no matching claim and assert `FactoryPanic` names the missing construction owner.

### Task 2: Repair malformed independent-owner witnesses

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/attribute_delete_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/method_call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/residual_aug_assign_sugar.py`

**Interfaces:**
- Consumes: each claim's existing `owns()` partition.
- Produces: witness sources that actually contain attribute deletion, positional plain call, positional method call, and a residual non-BitOr name aug-assign.

- [ ] Change only witness source programs and expected truthful/lying outcomes.
- [ ] Run the four focused owner-dispatch cases until registry and classifier agree.

### Task 3: Carry independently semantic nested sites through construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/annotation_union_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/import_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/slice_sugar.py`

**Interfaces:**
- Consumes: ordinary `ctx.build_body(site, SugarRole.TERM)` construction.
- Produces: annotation-union, import-alias, and slice witnesses whose real composite parents construct the independently semantic nested site through the catalog.

- [ ] Reframe annotation and slice witnesses around existing composite owners that already call `ctx.build_body` for those child sites.
- [ ] Replace direct import-alias value construction with factory-built alias bodies and reduce those bodies in source order.
- [ ] Run the three focused owner-dispatch cases and their nearest unit tests.

### Task 4: Retire the dead not claim

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/unary_op_sugar.py`
- Delete: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/not_op_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_unary_op_sugar.py`

**Interfaces:**
- Consumes: `UnaryOpSugar` as the sole owner of all four unary AST operators.
- Produces: a `not_return` witness registered by `UnaryOpSugar`, with no dead `NotOpSugar` claim or precedence edge.

- [ ] Move the `not_return` pair into `UnaryOpSugar.witnesses()` alongside its existing unary pair.
- [ ] Remove the `NotOpSugar` registration and obsolete precedence edge.
- [ ] Run the focused not-owner test and unary unit tests.

### Task 5: Verify and publish

**Files:**
- Verify all modified files above.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a focused green receipt, clean diff, commit, pushed branch, and non-closing PR.

- [ ] Run the eight-case registry/dispatch invariant plus the no-owner bad twin.
- [ ] Run nearest unit tests for annotation, alias/import, slice, delete, call/method, unary, and residual aug-assign.
- [ ] Run `git diff --check` and inspect the complete diff.
- [ ] Commit as T Savo, push `witness-owner-classifier-reconcile`, and open a PR whose body says `Part of #4397` and never closes or fixes it.
