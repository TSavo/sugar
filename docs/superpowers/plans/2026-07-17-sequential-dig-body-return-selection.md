# Sequential Dig Body Return Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact guarded return-or-raise selection from reduced
sequential outcomes while leaving every unbuilt or opaque shape loud.

**Architecture:** `SequentialDigBody` folds reduced guarded terminal outcomes
onto an unguarded fallback. A new `ExceptionalExitValue` reuses
`RaiseEffect`'s source-cited exceptional-exit term so a guarded raise remains
visible in the selected result without becoming a RuntimeEffect.

**Tech Stack:** Python 3.14, pytest, ProofIR formulas, Black 26.5.1.

## Global Constraints

- Part of #4968 and Part of #4684; never closes/fixes.
- Consume reduced semantic outcomes; never inspect vendor AST patterns.
- Unimplemented, opaque, stateful, or incomplete shapes stay `FactoryPanic`.
- No empty-success arm and no RuntimeEffect constructor.
- No full-corpus sweep.
- Author T Savo `<evilgenius@nefariousplan.com>`.
- Do not merge.

---

### Task 1: Pin guarded exceptional selection red

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_install_source_body_dig.py`

**Interfaces:**
- Consumes: `Complete(BlockValue((GuardedRaise,)))` and terminal
  `Complete(ReturnValue(...))` statement outcomes.
- Produces: a focused expectation for a guarded exceptional arm plus fallback
  return, and a mixed-state bad twin that must remain loud.

- [ ] Add `test_sequential_dig_constructs_guarded_raise_with_fallback`.
- [ ] Run that exact test and observe `owner=SequentialDigBody`.
- [ ] Add the mixed `GuardedRaise` plus `ScopeRebind` bad twin and confirm it
  already remains `FactoryPanic`.

### Task 2: Construct exceptional exit selection

**Files:**
- Create:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/exceptional_exit_value.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/raise_value.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/__init__.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: `RaiseEffect` plus `GuardedRaise.guards`.
- Produces: `ExceptionalExitValue.to_term(owner=...)` and a source-ordered
  `GuardedValue` fold over guarded return/raise exits.

- [ ] Extract `_exceptional_exit_term(effect)` from
  `_exceptional_exit_formula` without changing its rendered term.
- [ ] Implement immutable `ExceptionalExitValue(effect)` whose `to_term`
  delegates to `_exceptional_exit_term`.
- [ ] Accumulate `GuardedRaise` beside `GuardedReturn`; reject every other
  non-return contribution.
- [ ] Fold guarded raises as `ExceptionalExitValue` arms and guarded returns as
  their existing value arms onto the unguarded fallback.
- [ ] Run both discrimination arms and the existing sequential-dig tests green.
- [ ] Run exceptional-exit locus identity tests to prove source testimony is
  byte-preserved.

### Task 3: Add verdict-bearing witness

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/if_sugar.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_sugar_witness_instruments.py`

**Interfaces:**
- Consumes: `IfSugar.witnesses()` source with a guarded `raise` and unguarded
  fallback return.
- Produces: truthful `sat` and wrong-result `unsat` through the real solver.

- [ ] Add `if_raise_fallback_return` truthful/lying witness sources.
- [ ] Enroll the seed in `_GROUNDED_PRIMITIVE_REFUTE_SEEDS`.
- [ ] Run the exact witness parameter twice and require truthful `sat`, lying
  `unsat`.

### Task 4: Measure conservation and publish

**Files:**
- Measure:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`

**Interfaces:**
- Consumes: the eight named #4968 current-main representatives.
- Produces: owner-terminal before/after accounting with completed, later-loud,
  and silent buckets.

- [ ] Replay all eight representatives with the worktree-local release binary.
- [ ] Record `SequentialDigBody N -> 0`, completed count, each distinct later
  loud owner, and silent zero; if any representative remains
  `SequentialDigBody`, narrow the receipt honestly.
- [ ] Run Black 26.5.1, `git diff --check`, and focused tests.
- [ ] Rebase onto current `origin/main` and repeat the focused receipt.
- [ ] Commit as T Savo, push, open a non-closing draft PR with `Part of #4968`,
  post receipts, mark ready, and do not merge.
