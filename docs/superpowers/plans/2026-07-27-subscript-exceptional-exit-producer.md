# Subscript Exceptional-Exit Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit authenticated Subscript exceptional exits only from receiver floors whose source-visible semantics decide them, while keeping undecidable lookups named and loud.

**Architecture:** `SubscriptSugar` remains a sequencing/delegation shell. Concrete receiver floor implementations own success and exceptional-exit construction; undecidable receiver/key combinations use the existing construction-gap boundary. Assertion-With remains an unrelated ExitSet consumer.

**Tech Stack:** Python 3.14 AST/source construction, Sugar Floor/Outcome APIs, pytest through `bin/sugarbin run --task authenticated-python-lift`.

## Global Constraints

- Base exactly on main `675c5de7b`.
- Corpus is pandas 3.0.3 at `/Users/tsavo/sugar-defect-drain/.venv/lib/python3.14/site-packages/pandas`, manifest CID `sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0`.
- No vendor/name arm, assertion-With edit, side door, placeholder, sentinel, guessed exception type, generic runtime-effect fallback, ExitSet/outcome/generator edit, census, or demand-table rebuild.
- Undecided is a named third value, never False or Complete.
- Preserve construction panics, timeouts, native crashes, and unaccounted at zero.

---

### Task 1: Authenticate the concrete boundary

**Files:**
- Read: `pandas/tests/test_multilevel.py:157`
- Test: existing authenticated single-site launcher path

**Interfaces:**
- Consumes: pandas 3.0.3 corpus and shared demand-table shelf artifact.
- Produces: exact construct, panic, or typed-refusal boundary with inline exit status.

- [ ] Run the real site through the authenticated launcher without a bare `SourceFile` lift.
- [ ] Record whether Subscript construction emits `Completed`, `Halted(RaiseEffect)`, or a named refusal.
- [ ] If the shelf binary is absent and fallback is disabled, record that blocker and continue only with focused verification that does not rebuild the demand table.

### Task 2: Pin receiver-owned producer twins

**Files:**
- Test: the smallest existing focused Subscript floor test module under `implementations/python/sugar-lift-py-tests/tests/`.

**Interfaces:**
- Consumes: `SubscriptSugar.desugar`, concrete receiver `subscript` floors, `ExitSet`, and `RaiseEffect`.
- Produces: truthful exceptional-exit, lying success, and undecidable-refusal assertions.

- [ ] Add a 5-15 line reproducer derived from the verified pandas Subscript body.
- [ ] Add a truthful concrete failing lookup asserting the exact authenticated exception coordinate.
- [ ] Add a lying successful lookup asserting no exceptional edge; the assertion must fail if it observes the truthful edge.
- [ ] Add an undecidable receiver/key twin asserting the named refusal rather than a generic effect or completed value.
- [ ] Run the focused module with the repo-relative authenticated launcher and verify RED for the missing producer law.

### Task 3: Implement the general Subscript floor law

**Files:**
- Modify only the concrete receiver floor file(s) demonstrated by Task 2.
- Modify `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/subscript_sugar.py` only if evidence shows delegation itself loses an operand outcome; do not add receiver semantics there.

**Interfaces:**
- Consumes: concrete receiver contents and authenticated index/key floor.
- Produces: exact success, `Halted(RaiseEffect)` with native exception testimony, or named construction refusal.

- [ ] Implement the smallest receiver-owned distinction that turns the truthful twin green.
- [ ] Ensure symbolic/custom/opaque shapes take the named refusal path before any exception class is selected.
- [ ] Run the Task 2 module and verify truthful, lying, and undecidable twins pass.
- [ ] Search the production diff for vendor spellings, assertion-manager coupling, generic Subscript runtime effects, sentinels, and forbidden package edits.

### Task 4: Verify every touched package and mutation transaction

**Files:**
- Test: every focused module in packages modified by Tasks 2-3.

**Interfaces:**
- Consumes: final production diff and focused tests.
- Produces: fresh package results and clean/mutated/bites/reverted/clean evidence.

- [ ] Stage and commit the intended implementation so the worktree is clean.
- [ ] Apply the minimal inverse mutation to the producer law.
- [ ] Run the exact truthful test and verify it fails for the missing authenticated exceptional edge.
- [ ] Revert only that mutation, verify `git diff` is clean, and rerun the exact test green.
- [ ] Run focused tests for every touched package through the authenticated launcher with inline exit statuses.
- [ ] Confirm no timeout, construction panic, native crash, or unaccounted outcome occurred.

### Task 5: Publish without merging

**Files:**
- Commit: only the approved spec, plan, focused tests, and Subscript producer implementation.

**Interfaces:**
- Consumes: clean verified branch and exact author identity.
- Produces: pushed branch and open unmerged PR.

- [ ] Inspect `git status`, staged diff, and forbidden-symbol searches.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>` with a terse producer-law message.
- [ ] Push `fleet/subscript-floor-owner` to origin.
- [ ] Open a ready-for-review PR against `main` describing the boundary, twins, mutation transaction, focused results, and preserved zeros.
- [ ] Report branch head SHA and PR URL; do not merge.

