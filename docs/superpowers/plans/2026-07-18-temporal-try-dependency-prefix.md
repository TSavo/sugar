# Temporal Try dependency-prefix implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve earlier module declarations loaded by a selected module-level Try during install-source function construction.

**Architecture:** `_ctx_with_module_global_binds` extends its reverse dependency worklist from `SourceFragment` testimony, then replays the selected Try through the existing statement catalog and `TrySugar`. Execution-order selection remains one-way, so later declarations cannot backfill earlier uses.

**Tech Stack:** Python 3.14, sugar-lift factory/Sugar architecture, pytest, pinned Black 26.5.1, real Sugar solver witness harness.

## Global Constraints

- No inline `isinstance/ast` matcher and no bespoke `_is_` predicate.
- No RuntimeEffect, empty-success, or quiet `None` arm.
- Wrong-order declarations remain loud.
- Commit author is `T Savo <evilgenius@nefariousplan.com>`.
- PR body uses `Part of #5167` and never closes or fixes the issue.

---

### Task 1: Pin the dependency-prefix discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_module_sibling_defs.py`

**Interfaces:**
- Consumes: `audit_lift_file(..., recover_panics=True)`
- Produces: earlier-definition green arm and later-definition loud arm

- [ ] Add a source where an earlier `seed = 7` is loaded inside a module Try that binds `alias`, and a later function returns `alias`.
- [ ] Add the wrong-order twin with `seed = 7` after the Try.
- [ ] Run both tests and observe the earlier-definition arm fail at `TemporalContext(seed)` while the wrong-order arm remains loud.

### Task 2: Extend the existing selector

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/sugar_constructors.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_module_sibling_defs.py`

**Interfaces:**
- Consumes: `_module_declaration_bound_names(prior)` and `_names_in_fragment(prior)`
- Produces: a dependency-complete selected declaration prefix replayed by `TrySugar`

- [ ] For a selected Try, add its loaded names to `needed_work`.
- [ ] Add a `TrySugar` truthful/lying module dependency-prefix witness pair.
- [ ] Add the real-solver witness test.
- [ ] Run the discrimination green and confirm the wrong-order arm remains loud.

### Task 3: Measure and publish

**Files:**
- Create: `docs/ledgers/temporal-try-dependency-prefix-5167-2026-07-18.md`

**Interfaces:**
- Consumes: the two `_imp` representative files and exact local release binary
- Produces: named replay, conservation, and fresh witness receipt

- [ ] Replay both `_imp` representatives and record their next terminal.
- [ ] Replay all five starting representatives and count remaining TemporalContext terminals.
- [ ] Run focused discrimination, pinned Black 26.5.1, fresh witness, and claim-mass.
- [ ] Commit, push `fatal-corpus-temporalcontext-residual-v2`, and open a ready non-closing PR with `Part of #5167`.
