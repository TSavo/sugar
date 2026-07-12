# Unified Dunder Bridge Construction Drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the unified builtin and object-protocol dunder bridge through typed sugar construction while preserving loud unmatched arms.

**Architecture:** Add narrowly owning TERM/statement sugars that build every child through `SugarBody`, then dispatch to explicit methods on `ObjectValue`. Successful object slots construct `CallSiteValue` coordinates; genuinely runtime-undecidable values use named typed effects; missing methods or unsupported shapes remain `FactoryPanic` construction gaps. Do not restore the deleted generic operations dispatcher.

**Tech Stack:** Python 3.12, pytest, Sugar factory registry, ProofIR terms, battleaxe `bin/bpytest` and `bin/brun`.

## Global Constraints

- Start at `origin/main` commit `519570b39e5ab58b6b495816008c17c0bc492c35`.
- Never weaken assertions, skip tests, soften a factory panic, or use `Incomplete` for missing construction.
- Exclude decorated definitions, TemporalContext locals, BitOr annotation unions, builtin-name seeding, and abstract `RuntimeEffect` construction in `install_source_dig.py`.
- Preserve the datetime full-file census at 14/45 and prevent builtin-call regressions.
- Heavy validation runs detached on battleaxe with real exit codes.

---

### Task 1: Measure and pin the bridge root cause

**Files:**
- Test: `implementations/python/sugar-lift-py-tests/tests/test_builtin_dunder_bridge.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_getitem_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_dunder_frontier_audit.py`

**Interfaces:**
- Consumes: restored-suite dunder tests and current factory audit rows.
- Produces: exact baseline failure count, representative positive failure, bad-twin loud failure, and structural missing-owner evidence.

- [ ] Run the complete dunder module set with `bin/bpytest` detached on battleaxe and retain its exit code.
- [ ] Read the complete traceback bottoms for one builtin projection, one object slot, and the structural frontier.
- [ ] Confirm the common cause is absent typed construction after the deleted operations layer, not a stale assertion.

### Task 2: Construct builtin-to-dunder bridges

**Files:**
- Create or modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/*dunder*.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/object_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_builtin_dunder_bridge.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_display_conversion_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_repr_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_next_dunder.py`

**Interfaces:**
- Consumes: `SugarBody`, `ObjectValue.call_method_value`, `CallSiteValue`, `FactoryPanic`.
- Produces: explicit sugar owners for supported builtin projections and typed object method coordinates.

- [ ] Add a minimal positive test for a representative builtin projection if the restored test does not isolate ownership.
- [ ] Run it with `bin/bpytest` and confirm the expected missing-owner or wrong-coordinate red.
- [ ] Add explicit sugar ownership and typed object dispatch for the supported builtin projection family.
- [ ] Run positive and imported-name discrimination tests and confirm supported bridges pass while external/imported twins do not select the builtin owner.

### Task 3: Construct object protocol slots

**Files:**
- Create or modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/*dunder*.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/object_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_getattr_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_getitem_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_call_slot.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_context_manager_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_async_context_dunder.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_attribute_descriptor_dunders.py`

**Interfaces:**
- Consumes: constructed receiver and argument `SugarBody` values.
- Produces: explicit slot calls with receiver identity and ordered arguments, plus loud absence arms.

- [ ] Run one positive and one missing-method bad twin to capture red behavior.
- [ ] Add minimal slot-specific construction using `ObjectValue.call_method_value` and typed return values.
- [ ] Run the positive, bad-twin, and structural ownership tests; confirm the bad twin still raises `FactoryPanic`.
- [ ] Repeat only for slot families sharing the same construction mechanism until the unified cluster is drained.

### Task 4: Verify measurements and publish

**Files:**
- Modify only if required by truthful current ownership: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/collect_dunder_frontier.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_dunder_frontier_audit.py`

**Interfaces:**
- Consumes: completed bridge construction.
- Produces: focused totals, datetime and builtin-call non-regression receipts, pandas frontier delta/total/conservation, commit, pushed branch, and PR.

- [ ] Run the complete dunder cluster via detached `bin/bpytest`, poll, and record the real exit code and delta.
- [ ] Run datetime 14/45 and builtin-call regression slices via detached `bin/bpytest`.
- [ ] Run the pandas frontier via detached `bin/brun`, poll, and verify summary/report conservation.
- [ ] Inspect `git diff`, commit as `T Savo <evilgenius@nefariousplan.com>`, push, and open a non-merged PR containing `Part of #4208`, `Part of #4102`, and the required Claude Code footer.
