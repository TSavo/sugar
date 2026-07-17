# If Continuing-Path Join Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve reduced block fall-through testimony so nested conditional
scope joins construct every binding present on all continuing paths.

**Architecture:** `BlockSugar` computes a `can_fall_through` bit from reduced
`FollowStep` outcomes and stores it on `BlockValue`. `PredicateValue` and
`TrySugar` consume this semantic testimony instead of inferring whole-branch
termination from flattened exceptional posts.

**Tech Stack:** Python 3, dataclasses, pytest, Sugar Python lift factory.

## Global Constraints

- Construct from actual reduced outcomes; never inspect the AST to infer path completion.
- RuntimeEffect is permitted only for genuine runtime dependence through RuntimeOperand.
- Unimplemented or missing binding machinery remains a loud FactoryPanic.
- No full-corpus sweep; use the bounded named representative.
- Pinned formatter: black 26.5.1.

---

### Task 1: Pin nested continuing-path behavior

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py`

**Interfaces:**
- Consumes: `audit_lift_file(source, filename, hold_panic=False)`.
- Produces: a regression pair for complete continuing joins and missing-binding panic.

- [ ] **Step 1: Write the failing discrimination test**

Add a nested `if/elif/else` fixture where the first and final arms bind
`result`, the middle arm raises, and code after the conditional returns
`result`. Assert the lifted function contains the return rather than a
`TemporalContext` panic.

- [ ] **Step 2: Write the loud bad twin**

Remove the assignment from one continuing arm and assert
`owner=TemporalContext observed=result requested=value`.

- [ ] **Step 3: Run both tests red**

Run:

```bash
.venv-fatal-next/bin/pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py \
  -k 'nested_continuing_path'
```

Expected: the complete twin fails with the current `TemporalContext(result)`
panic; the bad twin passes because the floor remains loud.

### Task 2: Carry reduced fall-through testimony

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/block_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/block_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/predicate_value.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_sugar.py`

**Interfaces:**
- Produces: `BlockValue.can_fall_through: bool`.
- Consumes: `Outcome.follow() -> FollowStep`.

- [ ] **Step 1: Extend BlockValue**

Add a defaulted `can_fall_through: bool = True` field so existing direct
constructors remain source-compatible.

- [ ] **Step 2: Compute testimony once**

Have `BlockSugar._collect_iterative` return the entries, final context, and a
boolean. Set false only when a reduced statement returns a non-continuing
`FollowStep`; set true when reduction reaches the end.

- [ ] **Step 3: Consume testimony in PredicateValue**

Replace `any(entry.post_contribution())` branch-exit inference with
`not branch_record.can_fall_through`.

- [ ] **Step 4: Align TrySugar**

Make `_record_can_fall_through` return the `BlockValue` testimony when present,
retaining the existing structural fallback for non-block records.

- [ ] **Step 5: Run discrimination green**

Run the Task 1 command. Expected: complete twin passes and bad twin stays loud.

### Task 3: Verify bounded receipts and publish

**Files:**
- Test: `implementations/python/sugar-lift-py-tests/tests/test_branch_scope_join.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_try_sugar.py`

**Interfaces:**
- Consumes: current-main pandas `core/apply.py`.
- Produces: conservation and witness receipts for issue and PR.

- [ ] **Step 1: Run focused regression suites**

Run the branch-scope tests and focused try continuing-path tests.

- [ ] **Step 2: Run truthful/lying witness**

Run the existing `IfSugar` witness pair and require truthful `sat`, lying
`unsat`.

- [ ] **Step 3: Replay the named representative**

Run `corpus_fatal_triage.py --child-file <pandas>/core/apply.py --child-rel
pandas/core/apply.py`. Record the new terminal or completion and conservation;
silent must be zero.

- [ ] **Step 4: Format and commit**

Run black 26.5.1 on touched Python files, `git diff --check`, and commit as
T Savo `<evilgenius@nefariousplan.com>`.

- [ ] **Step 5: Publish**

Push `if-continuing-path-join`, open a non-closing draft PR with `Part of
#4837`, post receipts, then mark it ready. Do not merge.

