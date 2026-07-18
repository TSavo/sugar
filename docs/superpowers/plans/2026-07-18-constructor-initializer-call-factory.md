# Constructor Initializer Call Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route initializer calls through one factory-owned recognizer and remove every inline AST classifier from `constructor_call_sugar.py`.

**Architecture:** `SourceFragment` recognizes initializer call sites and other source shapes at the factory grammar boundary. `ConstructorCallSugar` consumes typed fragments and call testimony only.

**Tech Stack:** Python 3.12+, pytest, Sugar factory and SourceFragment APIs

## Global Constraints

- Preserve loud `FactoryPanic` behavior for unrecognized or unauthenticated shapes.
- Add no RuntimeEffect and no empty-success arm.
- Preserve super, asserted, and explicit-base truthful/lying witness pairs.
- `constructor_call_sugar.py` must contain zero `ast.*` references.

---

### Task 1: Add the stable-zero side-door instrument

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`

**Interfaces:**
- Consumes: the source text of `constructor_call_sugar.py`
- Produces: `test_constructor_call_sugar_has_no_inline_ast_shape_classifiers`

- [ ] Add a test that rejects `ast.*`, `_is_exact_super_init_node`,
  `_is_exact_super_init_fragment`, `_explicit_imported_base_initializer`, and
  `_ast_dotted_name`.
- [ ] Run the test and verify it fails on the current inline classifiers.

### Task 2: Move initializer recognition to SourceFragment

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/source_fragment.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/constructor_call_sugar.py`

**Interfaces:**
- Produces: `InitializerCallSite`
- Produces: `SourceFragment.initializer_call_site(receiver_name, declared_bases)`
- Consumes: typed call testimony in statement-door and rewrite logic

- [ ] Add the typed initializer-call testimony and one recognizer at the
  SourceFragment grammar boundary.
- [ ] Replace super, explicit-base, and self-method classifiers with that
  testimony.
- [ ] Move remaining statement and binding shape questions behind typed
  SourceFragment accessors.
- [ ] Delete the retired helpers and the `ast` import.
- [ ] Run the side-door instrument and focused discrimination green.

### Task 3: Verify and publish

**Files:**
- Test: `implementations/python/sugar-lift-py-tests/tests/test_constructor_call_evidence.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_claim_mass_tripwires.py`

**Interfaces:**
- Consumes: a provenance-matched local Sugar binary
- Produces: focused, witness, claim-mass, and static-audit receipts

- [ ] Run the focused constructor evidence discrimination.
- [ ] Build the exact local binary.
- [ ] Run super, asserted, and explicit-base truthful/lying witnesses.
- [ ] Run claim-mass tripwires.
- [ ] Confirm `rg 'ast\\.|_is_exact_super_init' constructor_call_sugar.py`
  returns no matches.
- [ ] Commit as T Savo, push, and open a non-closing PR.
