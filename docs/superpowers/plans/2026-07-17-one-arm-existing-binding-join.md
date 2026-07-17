# One-Arm Existing-Binding Join Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact post-`if` values for existing bindings changed by a
continuing one-arm conditional.

**Architecture:** `PredicateValue` will classify changes by comparing the
reduced pre-branch and branch scopes. Existing names become definite
`GuardedValue` joins; branch-only names retain the existing guarded binding.

**Tech Stack:** Python 3, pytest, Sugar Python lift factory, Z3 witness harness.

## Global Constraints

- Construct from reduced semantic outcomes, not AST inspection.
- Branch-only, opaque, and incomplete values stay loud.
- Add no RuntimeEffect constructor and no empty-success path.
- Use only focused tests and the bounded named representative replay.

---

### Task 1: Red discrimination and bad twin

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py`

**Interfaces:**
- Consumes: `compose_block`, `GuardedValue`, and a seeded `TemporalContext`.
- Produces: a failing regression that requires the existing-binding join.

- [ ] **Step 1: Write the failing positive test**

Construct:

```python
block = compose_block(
    "    if p:\n        value = 'changed'\n",
    {
        "p": SymbolicValue(make_var("p")),
        "value": StringValue("prior"),
    },
)
```

Extend an initially seeded scope and assert that `value` is
`GuardedValue(p, "changed", "prior")`.

- [ ] **Step 2: Confirm the positive test is red**

Run:

```bash
.venv-lane/bin/pytest implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py::test_one_arm_existing_binding_joins_changed_and_prior_values -q
```

Expected: failure because the current implementation retains the old definite
binding.

- [ ] **Step 3: Run the bad twin**

Run:

```bash
.venv-lane/bin/pytest implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py::test_one_arm_binding_read_stays_loud -q
```

Expected: pass with the branch-only name still producing `FactoryPanic`.

### Task 2: Construct the reduced-scope join

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/predicate_value.py`

**Interfaces:**
- Consumes: the branch scope and the temporal scope before the branch.
- Produces: `(joined_bindings, guarded_bindings, joined_effects)` for a
  continuing one-arm conditional.

- [ ] **Step 1: Split existing and branch-only bindings**

For changed names present in the pre-branch scope, answer both values and
construct:

```python
GuardedValue(guard, branch_answer.value, prior_answer.value)
```

For names absent from the pre-branch scope, preserve
`(guard, name, branch_answer.value)` in `guarded_bindings`.

- [ ] **Step 2: Preserve incomplete answers**

Guard an incomplete branch answer with `guard`; guard an incomplete prior
answer with `not_(guard)`. Do not add a joined success value for an incomplete
pair.

- [ ] **Step 3: Run focused tests**

Run the positive and bad-twin tests together, then the complete
`test_branch_scope_join.py` file. Expected: all pass.

### Task 3: Add and verify a verdict-bearing witness

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/if_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py`

**Interfaces:**
- Produces: `if_one_arm_existing_binding_join`, with truthful SAT and lying
  UNSAT twins.

- [ ] **Step 1: Add the witness pair**

Use a function with an existing value conditionally overwritten, then return
that value. The truthful twin asserts the selected result; the lying twin
asserts a different result.

- [ ] **Step 2: Add the solver-harness test**

Locate the pair by name and assert:

```python
assert truthful.verdict == pair.truthful.expected == "sat"
assert lying.verdict == pair.lying.expected == "unsat"
```

- [ ] **Step 3: Run the witness fresh**

Run only the new witness test after the final rebase. Expected: truthful SAT,
lying UNSAT.

### Task 4: Named representative receipt and publication

**Files:**
- Modify only if required by established receipt convention: tracking issue or
  PR body text.

**Interfaces:**
- Consumes: the full pandas
  `pandas/tests/tseries/offsets/test_business_hour.py` representative.
- Produces: terminal conservation and a ready non-closing PR.

- [ ] **Step 1: Replay the named representative**

Use the provenance-matched local release binary and private editable kit.
Record owner `SequentialDigBody` terminals before and after, completed versus
advanced-to-distinct-loud-front, and silent zero.

- [ ] **Step 2: Run formatting and focused regression**

Run pinned Black 26.5.1 on changed Python files and the focused branch-join
tests.

- [ ] **Step 3: Rebase and rerun fresh receipts**

Rebase on current `origin/main`, rebuild the provenance-matched binary, and
rerun the discrimination, witness, and named representative.

- [ ] **Step 4: Commit and publish**

Commit as `T Savo <evilgenius@nefariousplan.com>`, push the branch, and open a
ready non-closing PR whose body includes `Part of #5087` and `Part of #4684`.
Do not merge.
