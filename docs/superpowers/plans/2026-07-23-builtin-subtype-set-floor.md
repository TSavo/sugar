# Builtin Subtype and Finite-Set Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct authenticated `issubclass` and finite-set semantics on the Python floor so installed-source effect boundaries derive without package/name gates.

**Architecture:** Extend the existing `FloorValue` operation dispatch, authenticated builtin temporal bindings, class base graph, tuple disjunction, and constructed `SetValue`. Closed ground cases return constructed floor values; symbolic cases return typed predicate obligations; unsupported native cases retain typed loud outcomes. Installed-source manager derivation consumes the same predicate path for every provider.

**Tech Stack:** Python 3.12, dataclass floor values, ProofIR terms/predicates, pytest, repo IDD instruments, battleaxe `bin/bpytest` and `bin/brun`.

## Global Constraints

- Builtins get meaning through the Python FLOOR as CLOSED semantic operations.
- No generic opaque-builtin-result witness, name recognition, vendor arm, fabricated result, compatibility evaluator, or manager-specific branch.
- Witnesses authenticate operands, result, Python runtime identity, and semantic operation.
- Symbolic subtype and membership relations emit typed obligations; opaque/native behavior stays loud.
- Preserve sole construction path, `h = h(p)`, zero new construction-side-door findings, zero panic catches, and no timeout increase.
- Heavy validation runs only on battleaxe.
- Rebase onto current `origin/main` before requesting review; push but do not merge.

---

### Task 1: Executable architectural and acceptance instrument

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/builtin_closed_operation_instrument.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_builtin_closed_operation_instrument.py`

**Interfaces:**
- Consumes: repository root and Python AST.
- Produces: `BuiltinClosedOperationReport` with offender rows and stable-zero `R` axes for side doors, name/vendor gates, generic verdict witnesses, panic catches, and missing acceptance twins.

- [ ] Write planted positive and negative fixture tests for each axis and require output rows to name the floor replacement.
- [ ] Run the test and verify RED because the collector does not exist.
- [ ] Implement deterministic AST collection over production files and acceptance-test names; print every offender and current `R`, exiting nonzero while any axis is nonzero.
- [ ] Run the instrument tests and verify GREEN; run it once on base and retain the numeric JSON receipt for later base/head comparison.
- [ ] Commit the instrument independently.

### Task 2: Authenticated closed-operation testimony and builtin coordinate

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/closed_operation_witness.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/builtin_semantic_callable.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/__init__.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/temporal/builtin_name_bindings.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_builtin_closed_operation_witness.py`

**Interfaces:**
- Produces: `ClosedSemanticOperationWitness.mint(runtime_identity, operation, operands, result)` and `verify(...)`; `BuiltinSemanticCallable(runtime_identity, operation)` implementing `callable_application_with` for exactly `python.issubclass`.

- [ ] Write truthful and four lying witness twins (operand, result, runtime identity, operation), plus shadowed-name and opaque-arity callable tests.
- [ ] Run the focused test and verify the imports/dispatch fail.
- [ ] Implement CID-based closed witness mint/verify and seed `issubclass` only in the authenticated builtin temporal vocabulary.
- [ ] Run the focused test and verify all truthful/lying twins pass.
- [ ] Commit the testimony and callable coordinate.

### Task 3: Authenticated subtype graph and tuple disjunction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/class_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/tuple_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/symbolic_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_builtin_subtype_floor.py`

**Interfaces:**
- Produces: `ClassValue.test_python_subtype(supertype, site)`; `TupleValue.test_python_subtype(subtype, site)`; typed `python.subtype` predicates for authenticated symbolic operands.

- [ ] Write RED tests for direct, transitive, unrelated, and renamed class graphs; tuple true/false partition; symbolic obligation; non-type and opaque/native loud cases.
- [ ] Implement cycle-safe traversal over constructed `ClassValue.bases`, using the existing tuple predicate collector for disjunction and `PredicateValue(atomic("python.subtype", ...))` for lawful symbolic relations.
- [ ] Run the focused subtype tests and verify GREEN.
- [ ] Commit subtype semantics.

### Task 4: Constructed finite-set membership and algebra

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/set_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/set_literal_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_builtin_finite_set_floor.py`

**Interfaces:**
- Produces: `SetValue.contains`, `bitwise_or`, `bitwise_and`, and `subtract`; typed `python.set.contains` predicates where constructed equality is symbolic.

- [ ] Write RED tests for present/absent membership, union, intersection, difference, symbolic membership obligation, duplicate handling, and opaque/native loud twins.
- [ ] Implement member comparison through constructed equality outcomes only; fold all-ground results and combine symbolic equality predicates without using host dataclass equality as semantic authority.
- [ ] Run the focused set tests and verify GREEN.
- [ ] Commit finite-set semantics.

### Task 5: Installed-source effect-boundary derivation

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_manager_construction.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_sole_path_manager_construction.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_installed_source_builtin_boundaries.py`

**Interfaces:**
- Consumes: the floor predicate produced by authenticated `issubclass`.
- Produces: existing `EffectBoundarySemanticsV1` for installed-source `pytest.raises` and `contextlib.suppress`, with no provider-name branch.

- [ ] Add RED installed-source tests for matching consumed, wrong type propagated, absent effect failed, tuple partition, and renamed equivalent source; assert the same floor operation witness is present.
- [ ] Extend source expression construction only where required to project authenticated builtin call predicates; do not add provider dispatch.
- [ ] Run manager-focused tests and verify GREEN, including an AST assertion that production contains no `pytest.raises` or `contextlib.suppress` decision gate.
- [ ] Commit manager integration.

### Task 6: Receipts, rebase, and review PR

**Files:**
- Modify only if receipts are conventionally checked in: `docs/receipts/2026-07-23-builtin-subtype-set-floor.md`

**Interfaces:**
- Produces: base/head instrument JSON, focused pytest receipt, battleaxe broad/battleaxe receipt, timeout and panic-catch comparison, rebased branch, and open PR.

- [ ] Run the complete focused acceptance set on battleaxe with `bin/bpytest`, capture the real exit code, and inspect summary lines.
- [ ] Run the repo-prescribed battleaxe side-door and census commands with `bin/brun`; compare numeric base/head JSON and report measured `Delta R` without inferring zeros from process completion.
- [ ] Fetch `origin/main`, rebase, rerun the focused and invariant receipts on battleaxe, and confirm a clean worktree.
- [ ] Verify author identity is `T Savo <evilgenius@nefariousplan.com>`, push with upstream, open a non-draft review PR, and request review without merging.
