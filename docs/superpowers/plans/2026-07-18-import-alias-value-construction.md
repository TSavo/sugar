# Import Alias Value Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct exact qualified import coordinates and source-backed truth
values for the eight #5137 representatives without weakening loud failure.

**Architecture:** Static two-argument `getattr` remains routed through
install-source resolution, then uses a narrow authenticated import-coordinate
fallback. From-import truth continues through `resolve_install_source_value`
and delegates only after a concrete floor value is attached.

**Tech Stack:** Python 3.12, pytest, Sugar Python lift factory, Rust release
CLI, Z3 witness harness.

## Global Constraints

- Never use a ground-value RuntimeEffect.
- Never add empty success or quiet a `None` arm.
- Effect only genuine runtime through an existing sealed door.
- A genuinely unresolvable alias stays loud.
- Re-pin claim mass loudly if the direct-pytest tripwire moves.
- Replay only the eight named representatives; do not run a full corpus sweep.

---

### Task 1: Red discrimination

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/tests/test_import_alias_residual_floors.py`

**Interfaces:**
- Consumes: `GetattrBuiltinSugar._finish_static`,
  `resolve_install_source_value`, and `ImportAliasValue.truth`.
- Produces: regression tests for qualified attribute construction,
  source-backed flag truth, and loud unresolved twins.

- [ ] Add a concrete imported-class attribute test expecting an exact
  `python:import_alias("now", "pandas.Timestamp.now")` coordinate.
- [ ] Add a missing qualified attribute test expecting `FactoryPanic` owned by
  `ImportAliasValue`.
- [ ] Add tests expecting constructed truth for
  `pandas.core.computation.check.NUMEXPR_INSTALLED` and
  `pandas.compat.HAS_PYARROW`.
- [ ] Retain the existing `no_such_pkg.missing` and unresolved-from-import truth
  cases as loud discrimination.
- [ ] Run the named tests through `bin/bpytest` and record the expected red
  failures before changing production code.

### Task 2: Exact qualified attribute construction

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/import_alias_value.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/getattr_builtin_sugar.py`
- Test:
  `implementations/python/sugar-lift-py-tests/tests/test_import_alias_residual_floors.py`

**Interfaces:**
- Produces:
  `ImportAliasValue.qualified_attribute(name: str, site) -> ImportAliasValue | None`.
- Consumes: the source-stated `import_target` and a static attribute name.

- [ ] Import the exact target and authenticate the receiver's concrete object
  identity without claiming the requested attribute lookup succeeds.
- [ ] Return `ImportAliasValue(f"{target}.{name}", name,
  import_target=f"{target}.{name}")` for the authenticated coordinate.
- [ ] In `_finish_static`, use this coordinate only after
  `resolve_install_source_value` returns `None`; otherwise call the existing
  loud `getattr_static`.
- [ ] Run the qualified-attribute and missing-attribute tests green.

### Task 3: Source-backed truth construction

**Files:**
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/install_source_dig.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/import_from_sugar.py`
- Modify:
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/single_importfrom_sugar.py`
- Test:
  `implementations/python/sugar-lift-py-tests/tests/test_import_alias_residual_floors.py`

**Interfaces:**
- Consumes: source assignments, guarded assignments, and definite reexports.
- Produces: a single concrete `FloorValue` for each resolvable imported flag,
  or `None` when construction is not unique.

- [ ] Reproduce both flag misses with direct resolver tests.
- [ ] Extend only the missing source declaration/reexport shape revealed by the
  red failures.
- [ ] Verify each flag's `ImportAliasValue.truth` delegates to the constructed
  value.
- [ ] Run both flag tests and the unresolved truth bad twin green.

### Task 4: Receipts and publication

**Files:**
- Modify only if claim mass moves:
  `implementations/python/sugar-lift-py-tests/tests/claim_mass_corpus.py`

**Interfaces:**
- Produces: bounded replay conservation, discrimination, fresh witness, branch,
  commit, and non-closing draft PR.

- [ ] Run the focused import-alias test files.
- [ ] Run the direct-pytest claim-mass tripwire.
- [ ] Replay the six `ImportAliasValue` and two `ImportAliasValue.truth` files;
  report every terminal movement and `silent=0`.
- [ ] Build a fresh local CLI and record its source provenance.
- [ ] Run a truthful/lying import-alias witness and require distinct expected
  verdicts.
- [ ] Format changed Python with the repository-pinned formatter.
- [ ] Commit as `T Savo <evilgenius@nefariousplan.com>`, push
  `fatal-corpus-import-alias-value`, and open a non-closing draft PR containing
  `Part of #5137`. Do not merge it.
