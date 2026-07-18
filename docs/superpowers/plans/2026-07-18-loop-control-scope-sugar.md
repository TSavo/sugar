# Loop Control Scope Sugar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote loop/control scope classification from `SourceFragment` into `LoopControlScopeSugar` and delete the factory walker.

**Architecture:** A focused Sugar module owns and computes the typed loop/control testimony. Existing loop, try, and comprehension Sugars call that recognizer; `SourceFragment` no longer classifies the shapes. A static sweep records all remaining factory side-door candidates.

**Tech Stack:** Python 3.14, Python `ast`, Sugar claim/factory framework, pytest.

## Global Constraints

- No suppression, runtime effect, empty success, or quiet fallback.
- No classification helper remains in `factory/source_fragment.py`.
- Raw raise/error bodies are file-only.
- The PR remains non-closing and says `Part of #5207`.

---

### Task 1: Pin the promotion red

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_loop_control_side_doors.py`

**Interfaces:**
- Consumes: existing loop/control fixtures in this test module.
- Produces: executable requirements for `LoopControlScopeSugar`.

- [ ] Add tests asserting the old `SourceFragment` method is absent and the
  new recognizer owns For, While, Block/finally, and comprehension targets.
- [ ] Run the named tests with output redirected to
  `/tmp/5207-red.log`; require failure because the old method remains and the
  new Sugar module does not exist.
- [ ] Commit the red test together with its implementation only after green.

### Task 2: Promote and delete the walker

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/loop_control_scope_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/source_fragment.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/for_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/for_else_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/while_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/comprehension_clauses.py`

**Interfaces:**
- Produces: `LoopControlScopeSugar.owns(site) -> bool`.
- Produces: `LoopControlScopeSugar.classify(site, *, target_name=None, entry_reads=()) -> LoopControlScopeClassification`.

- [ ] Move the typed classification and its walker unchanged into the Sugar
  module.
- [ ] Make `owns` explicit for the shapes exercised by loops, finally blocks,
  and comprehension targets.
- [ ] Route all five consumers through `LoopControlScopeSugar.classify`.
- [ ] Delete `SourceFragment.classify_loop_control_scope` and the factory-owned
  classification type.
- [ ] Run the named side-door and loop-control tests; require green.

### Task 3: Inventory every remaining SourceFragment side door

**Files:**
- Create: `docs/python-source-fragment-side-door-inventory-2026-07-18.md`

**Interfaces:**
- Consumes: AST scan of `factory/source_fragment.py`.
- Produces: exact line, family, disposition, and replacement owner for every
  match.

- [ ] Parse `source_fragment.py` and record every `ast.walk`, AST visitor,
  `isinstance(..., ast.*)`, IR/floor constructor, and `.reduce` site.
- [ ] Mark the loop/control family promoted; flag all other semantic
  classification/construction sites for follow-on #5204 STEP 2 lanes.
- [ ] Record grammar-only access separately but do not exempt it silently.

### Task 4: Verify and publish

**Files:**
- Verify all files above.

**Interfaces:**
- Produces: focused pytest receipt, zero-tolerance receipt, draft PR.

- [ ] Run focused loop/control, comprehension, try, for, while, and side-door
  tests with verbose output redirected to files.
- [ ] Fetch/rebase the #5204 STEP 1 instrument when available and run its exact
  direct pytest target; report honestly if it has not landed.
- [ ] Run formatting and `git diff --check`.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>`.
- [ ] Push and open a draft non-closing PR with `Part of #5207`.

### Task 5: Harden the baseline-free SourceFragment instrument

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/factory_zero_tolerance.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_factory_zero_tolerance.py`

**Interfaces:**
- Produces: a live semantic-classifier offender set for `SourceFragment`.

- [ ] Detect meaning-bearing AST classifiers, walkers, and visitors while
  preserving child-fragment projection as structural.
- [ ] Run the focused instrument and record the named red set.
- [ ] Assert only stable zero; add no baseline or accepted-count threshold.

### Task 6: Promote every remaining semantic family

**Files:**
- Modify: registered annotation, Call, Assign/For/With, Try, BoolOp/format,
  test-function, constructor, and loop-control Sugars.
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_fragment.py`
- Modify: focused witness tests for each owning Sugar.

**Interfaces:**
- Consumes: structural child projections from `SourceFragment`.
- Produces: Sugar-owned recognizers whose owned cases construct or emit a
  genuine typed effect.

- [ ] Add a failing good/bad twin for one semantic family.
- [ ] Move that classifier into its registered Sugar owner and delete the
  SourceFragment method.
- [ ] Run the twin and semantic-classifier instrument.
- [ ] Repeat until the SourceFragment semantic count is zero.

### Task 7: Hardened verification and PR update

- [ ] Run the baseline-free instrument; require SourceFragment semantic zero.
- [ ] Run bounded named replay, conservation (`silent=0`), discrimination, and
  fresh provenance-matched witnesses.
- [ ] Update the inventory with every registered Sugar owner.
- [ ] Commit as T Savo and update open non-closing PR #5215.
