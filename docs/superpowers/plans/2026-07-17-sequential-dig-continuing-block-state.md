# Sequential Dig Continuing Block State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select exact guarded exits across an authenticated continuing
`BlockValue` that also carries already-threaded scope testimony.

**Architecture:** Extend the existing reduced-outcome fold with one predicate
over `BlockValue` continuation and contribution types. Do not inspect AST
shape or add an effect.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, Black 26.5.1.

## Global Constraints

- RuntimeEffect is forbidden for this fully reduced shape.
- Custom mixed outcomes, halted blocks, opaque entries, and incomplete
  outcomes remain loud.
- Preserve source-order guard folding and use the worktree-local `.venv-lane`.

---

### Task 1: Reduced-outcome discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_install_source_body_dig.py`

**Interfaces:**
- Consumes: `SequentialDigBody.desugar(ctx)`, `Complete(BlockValue(...))`.
- Produces: a positive continuing-block test and a halted-block panic twin.

- [x] Add a continuing `BlockValue` with `GuardedRaise`, exact rebinds, and a
      following unguarded `ReturnValue`.
- [x] Add the same record with `can_fall_through=False` as the loud twin.
- [x] Run both tests and confirm the positive arm fails at
      `owner=SequentialDigBody` while the twin already panics.

### Task 2: Exact block-state construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`

**Interfaces:**
- Consumes: reduced `BlockValue.can_fall_through` and contribution entries.
- Produces: guarded exit selection over an exact later fallback.

- [x] Accept only a continuing `BlockValue` whose non-exits are rebinds or
      existing support testimony.
- [x] Run the discrimination and the unchanged mixed-outcome regression green.
- [x] Add and run a truthful/lying real-solver witness.

### Task 3: Named receipt and publication

**Files:**
- Modify: this plan only to record completed steps.

**Interfaces:**
- Consumes: current-main pandas vendor files and the focused tests.
- Produces: conservation receipt and a ready non-closing PR for #5087.

- [x] Replay both named representatives and record owner movement with
      `silent=0`.
- [ ] Rebase on final `origin/main`; rerun the witness fresh.
- [ ] Run the RuntimeEffect constructor census only if an effect site changed,
      and run Black 26.5.1.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>`, push, open a draft PR
      with `Part of #5087`, then mark it ready.
