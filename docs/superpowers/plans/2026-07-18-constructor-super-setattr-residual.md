# Constructor super-setattr residual implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct the exact `super().__setattr__("name", value)` initializer binding through the #5189 factory recognizer.

**Architecture:** `SourceFragment.initializer_call_site` remains the only syntax recognizer and emits typed testimony. The constructor-scoped `ConstructorInitializerCallSugar` claim consumes that testimony and constructs a scope rebind; unsupported forms remain loud.

**Tech Stack:** Python 3.14, sugar-lift factory/Sugar architecture, pytest, pinned Black 26.5.1, real Sugar solver witness harness.

## Global Constraints

- No inline AST matcher or bespoke `_is_` predicate in `constructor_call_sugar.py`.
- No RuntimeEffect, empty-success, or quiet `None` arm.
- Non-ground attribute names and unsupported call shapes remain `FactoryPanic`.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.
- PR body uses `Part of #5151` and never closes or fixes the issue.

---

### Task 1: Red discrimination and recognizer testimony

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_source_fragment.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/source_fragment.py`

**Interfaces:**
- Consumes: `SourceFragment.initializer_call_site(receiver_name, declared_bases)`
- Produces: `InitializerCallSite(kind="super_setattr", call=..., target=<ground attribute>)`

- [ ] Add a recognizer test for exact ground-name `super().__setattr__`.
- [ ] Add a wrong-twin recognizer test for a non-ground attribute name.
- [ ] Add constructor outcome tests proving ground construction and loud non-ground refusal.
- [ ] Run the tests and observe the expected red failure before production edits.
- [ ] Extend `initializer_call_site` minimally and rerun the recognizer tests green.

### Task 2: Factory construction and witness

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`

**Interfaces:**
- Consumes: typed `super_setattr` testimony and the constructor temporal context
- Produces: `SuperSetAttrApply.desugar(ctx) -> Complete(ScopeRebinds(...))`

- [ ] Add the truthful/lying `source_body_constructor_super_setattr` witness pair.
- [ ] Add the real-solver witness test and observe red before implementation.
- [ ] Implement `SuperSetAttrApply` and route it through the dynamic factory claim.
- [ ] Keep unsupported `super().__setattr__` shapes outside the claim so they panic.
- [ ] Run discrimination and witness tests green.

### Task 3: Representative conservation and publication

**Files:**
- Create: `docs/ledgers/constructor-super-setattr-5151-2026-07-18.md`

**Interfaces:**
- Consumes: installed pandas 3.0.3 representative and local provenance-matched Sugar binary
- Produces: named replay and conservation receipt

- [ ] Replay `pandas/io/clipboard/__init__.py` before/after and record the owner transition.
- [ ] Run the no-inline-AST audit and confirm zero classifiers.
- [ ] Run focused constructor tests, pinned Black 26.5.1, fresh truthful/lying witness, and claim-mass tripwire if applicable.
- [ ] Commit, push `fatal-corpus-constructorcall-residual-v2`, and open a ready non-closing PR with `Part of #5151`.

