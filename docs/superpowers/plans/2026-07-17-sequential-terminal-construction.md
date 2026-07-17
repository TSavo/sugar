# Sequential Terminal Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct decidable sequential guarded-return results instead of
attempting to mint a ground RuntimeEffect.

**Architecture:** `SequentialDigBody` folds reduced `GuardedReturn` testimony
onto an unguarded fallback as nested `GuardedValue` nodes. Unsupported or
incomplete control-flow shapes remain loud.

**Tech Stack:** Python 3.14, pytest, ProofIR formulas, black 26.5.1.

## Global Constraints

- Part of #4855; never closes/fixes.
- Ground/unimplemented machinery must panic, never become RuntimeEffect.
- No full-corpus sweep.
- Author T Savo `<evilgenius@nefariousplan.com>`.
- Do not merge.

---

### Task 1: Pin reduced return folding

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_install_source_body_dig.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: ordered `GuardedReturn` and terminal `ReturnValue` contributions.
- Produces: `Complete(GuardedValue)` preserving source-order return selection.

- [ ] Add a focused guarded-return plus fallback test and retain the existing
  no-fallback panic bad twin.
- [ ] Run the focused test red at the rejected ground RuntimeEffect door.
- [ ] Replace `_control_flow_incomplete` for the decidable subset with a nested
  `GuardedValue` fold.
- [ ] Run both discrimination arms green.

### Task 2: Verdict evidence

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_install_source_body_dig.py`

**Interfaces:**
- Consumes: real-solver witness source with a symbolic early return.
- Produces: truthful `sat`, lying `unsat`.

- [ ] Add and run the truthful/lying witness.
- [ ] Run the RuntimeEffect constructor/evidence census and require zero
  failures.

### Task 3: Receipt and publish

**Files:**
- Measure:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`

**Interfaces:**
- Consumes: installed `numpy/f2py/symbolic.py`.
- Produces: named-terminal conservation for #4855.

- [ ] Replay the bounded representative and record where mass moves.
- [ ] Run Black 26.5.1 and `git diff --check`.
- [ ] Rebase on current `origin/main` and repeat focused receipts.
- [ ] Commit, push, open a non-closing draft PR with `Part of #4855`, post
  receipts, mark ready, and do not merge.
