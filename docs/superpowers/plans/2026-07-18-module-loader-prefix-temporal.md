# Module loader prefix TemporalContext implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct demanded module-loader bindings for provenance-authenticated install-source functions.

**Architecture:** Share one loader-prefix helper between `_module_import_temporal` and `_ctx_with_module_global_binds`. The latter consumes only demanded loader names before replaying selected statements through the existing catalog.

**Tech Stack:** Python 3.12.3, sugar-lift factory catalog, pytest, pinned Black 26.5.1, release Sugar witness harness.

## Global Constraints

- No inline AST matcher or bespoke `_is_` predicate.
- Untagged or provenance-mismatched functions remain loud.
- No RuntimeEffect, empty-success, or quiet `None` arm.
- Author is `T Savo <evilgenius@nefariousplan.com>`.
- Any PR is non-closing and says `Part of #5167`.

---

### Task 1: Pin loader-prefix discrimination

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_module_global_name_bind.py`

**Interfaces:**
- Consumes: `_tag_install_source`, `_ctx_with_formal_binds`
- Produces: tagged green arm and untagged loud arm

- [ ] Add a tagged function returning `__file__` and assert the exact `StringValue`.
- [ ] Add the same untagged function and assert `TemporalContext(__file__)` panics.
- [ ] Run both and confirm the tagged arm fails before implementation while the untagged arm stays loud.

### Task 2: Share and consume the loader prefix

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/sugar_constructors.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/statement_function_def_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_module_global_name_bind.py`

**Interfaces:**
- Produces: `module_loader_temporal(filename, *, demanded=None, temporal=None)`
- Consumes: authenticated filename from `_module_source_for_site`

- [ ] Extract the existing `__file__` and `__builtins__` loader bindings into the shared helper.
- [ ] Use the helper in `_module_import_temporal` for the complete module prefix.
- [ ] Use the helper in `_ctx_with_module_global_binds` for demanded loader names only.
- [ ] Add a `StatementFunctionDefSugar` truthful/lying witness and real-solver test.
- [ ] Run discrimination and witness green.

### Task 3: Measure and publish

**Files:**
- Create: `docs/ledgers/temporal-module-loader-prefix-5167-2026-07-18.md`

**Interfaces:**
- Consumes: five sealed #5121 representatives
- Produces: exact current-main residual and conservation receipt

- [ ] Replay the five representatives in Python 3.12.3 / NumPy 2.5.1 / pandas 3.0.3.
- [ ] Record completed, advanced-loud, unchanged-loud, and silent counts.
- [ ] Run focused pytest, Black 26.5.1, fresh provenance-matched witness, and claim-mass tripwires.
- [ ] Commit and push a non-closing `Part of #5167` PR if construction moves the frontier.
