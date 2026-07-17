# Contextualized Callable Self-Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct a deferred Python callable's own lexical binding from the exact `FunctionCallable` produced by its definition.

**Architecture:** `FunctionCallable.callsite` annotates a contextualized deferred body with the source-constructed callable. `ContextualizedDigBody` binds that one callable after restoring lexical context and curried arguments, while all unrelated missing names remain loud.

**Tech Stack:** Python 3.14, dataclasses, Sugar Python lift factory, pytest, Black 26.5.1.

## Global Constraints

- Construct or panic; never translate unimplemented machinery into a RuntimeEffect.
- RuntimeEffect arms are permitted only for genuinely runtime-dependent operands through RuntimeOperand.
- Use bounded named-representative replay; do not run a full corpus census.
- Preserve silent terminal count at zero.

---

### Task 1: Pin callable self-binding and its loud bad twin

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_statement_function_def_sugar.py`

**Interfaces:**
- Consumes: `_module_import_temporal`, `FunctionCallable.callsite`, and `force_floor`.
- Produces: one failing self-binding discrimination and one passing undefined-name bad twin.

- [ ] Add a fixture module whose function body reads its own name in a branch.
- [ ] Demand the constructed function's body floor and assert the self-name no longer raises `TemporalContext`.
- [ ] Add a twin whose body reads `never_defined` and assert its `TemporalContext` panic remains.
- [ ] Run both tests and record the self-binding test failing specifically on the missing own name.

### Task 2: Construct the lazy self-binding

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/function_callable.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: a `FunctionCallable` and `SugarBody[ContextualizedDigBody]`.
- Produces: a copied contextualized body with `callable_binding`, reduced under `name -> callable`.

- [ ] Add optional `callable_binding` testimony to `ContextualizedDigBody`.
- [ ] Bind that testimony after lexical restoration and argument overlay.
- [ ] In `FunctionCallable.callsite`, copy only contextualized bodies with the exact callable testimony.
- [ ] Run the discrimination and bad twin; require both green.

### Task 3: Add verdict witness and bounded receipt

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/statement_function_def_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_statement_function_def_sugar.py`

**Interfaces:**
- Consumes: `StatementFunctionDefSugar.witnesses()`.
- Produces: a recursive truthful/lying pair whose verdicts discriminate.

- [ ] Add a recursive callable witness pair.
- [ ] Run only that witness and require truthful SAT / lying UNSAT.
- [ ] Run the RuntimeEffect constructor/evidence invariant census.
- [ ] Replay installed `numpy/f2py/symbolic.py` and record conservation.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Commit, rebase on current main, repeat focused receipts, push, open a non-closing draft PR with `Part of #4868`, post the receipt, and mark ready.
