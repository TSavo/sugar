# Timeout and Singleton Fatal Residual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the decidable dict-unpack runtime effect and authenticated
pandas accessor-decorated class factory gap while preserving four genuine
bounded timeouts and every loud runtime/unknown-decorator floor.

**Architecture:** `DictLiteralSugar` delegates a source-resolved
`ImportAliasValue` to its resolved floor before the existing `DictValue` merge.
`ClassDefSugar` routes decorated-class ownership through the existing
`class_decorators_preserve_identity` factory recognizer, extended with
authenticated qualified pandas accessor registrars. The timeout instrument is
measurement-only.

**Tech Stack:** Python 3.14, pytest, Sugar Python floor/factory framework,
`corpus_fatal_triage.py`, local provenance-matched release Sugar binary.

## Global Constraints

- No timeout behavior or bound changes.
- Genuine runtime dict unpack remains `DictUnpackRuntimeEffect`.
- Unknown or class-replacing decorators remain a loud `python.factory` panic.
- No inline AST `isinstance` matcher and no bespoke `_is_*` / `_matches_*`
  predicate.
- Never ground-value effect, empty-success, or quiet the `None` arm.
- Raw panic/effect/error bodies go to files; terminal output is counts and
  file/owner tags only.
- Draft non-closing PR with `Part of #5194`; do not merge.
- Author `T Savo <evilgenius@nefariousplan.com>`.

---

### Task 1: Construct resolved dict-unpack aliases

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/dict_literal_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_dict_unpack_sugar.py`

**Interfaces:**
- Consumes: `ImportAliasValue.resolved_value: FloorValue | None`
- Produces: `_merge_expansion` delegation to a resolved `DictValue`

- [ ] **Step 1: Add a red unit test**

Construct an `ImportAliasValue` whose `resolved_value` is a finite
`DictValue`, feed it to `DictLiteralSugar._merge_expansion`, and assert a
complete merged `DictValue`.

- [ ] **Step 2: Add the runtime discrimination twin**

Construct an `ImportAliasValue` with `resolved_value=None`, write its effect
tag to `tmp_path`, and assert the result remains
`DictUnpackRuntimeEffect`.

- [ ] **Step 3: Run the two tests and verify red**

Run:

```bash
pytest -q implementations/python/sugar-lift-py-tests/tests/test_dict_unpack_sugar.py \
  -k 'resolved_import_alias or unresolved_import_alias'
```

Expected: resolved alias test fails because the alias is currently sent to the
runtime-effect door; unresolved twin passes.

- [ ] **Step 4: Implement minimal resolved-value delegation**

In `_merge_expansion`, replace an `ImportAliasValue` with its non-`None`
`resolved_value` before the existing `DictValue` branch. Do not add a success
path for unresolved or non-dict values.

- [ ] **Step 5: Run the focused tests green**

Expected: both tests pass; unresolved alias remains a typed effect.

---

### Task 2: Route accessor-decorated classes through the existing recognizer

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/sugar_constructors.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/class_def_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_class_def_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_module_global_name_bind.py`

**Interfaces:**
- Consumes: `SourceFragment.dotted_expr_name()` and source import declarations
- Produces: public
  `class_decorators_preserve_identity(statement: SourceFragment) -> bool`

- [ ] **Step 1: Add red recognizer and ownership tests**

Use source containing `import pandas as pd` and
`@pd.api.extensions.register_series_accessor("bad")`. Assert the existing
recognizer returns true and `ClassDefSugar.owns` returns true.

- [ ] **Step 2: Preserve loud discrimination**

Keep the existing unknown `@dec` class panic test and add a qualified unknown
decorator case. Capture panic testimony to a file and print no body.

- [ ] **Step 3: Run focused tests and verify red**

Run:

```bash
pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_class_def_sugar.py \
  implementations/python/sugar-lift-py-tests/tests/test_module_global_name_bind.py \
  -k 'accessor or decorated_class or identity_decorated'
```

Expected: authenticated accessor class is unowned; unknown decorators remain
loud.

- [ ] **Step 4: Extend the existing recognizer**

Rename `_class_decorators_preserve_identity` to the importable
`class_decorators_preserve_identity`. Add authenticated module-alias resolution
and the three exact pandas accessor registrar exports. Match decorators by
`SourceFragment.dotted_expr_name`; do not inspect raw AST nodes.

- [ ] **Step 5: Route `ClassDefSugar.owns` through the recognizer**

When decorators exist, return the recognizer result. Continue refusing class
keywords.

- [ ] **Step 6: Run focused tests green**

Expected: authenticated registrar constructs; unknown qualified and local
decorators remain loud.

---

### Task 3: Corpus conservation and fresh witness

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_timeout_singleton_residual.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/class_def_sugar.py`

**Interfaces:**
- Consumes: the seven exact #5194 files and `ClassDefSugar.witnesses()`
- Produces: aggregate disposition JSON with `silent=0` and a fresh
  accessor-decorated-class truthful/lying witness

- [ ] **Step 1: Add the seven-front replay instrument**

Gate it behind `SUGAR_FATAL_CORPUS_REPLAY=1`; run child stdout/stderr into
`tmp_path` files. Assert:

- four rows remain bounded timeouts unless #5191 retires them;
- `pandas/io/stata.py` is slow-only/completed;
- the two typed singleton owners retire;
- every input has exactly one disposition and `silent=0`.

- [ ] **Step 2: Add an accessor-class witness pair**

Add a `ClassDefSugar.witnesses()` pair whose prefix imports pandas, decorates a
class with `register_series_accessor`, and discriminates truthful from lying
return assertions.

- [ ] **Step 3: Run the bounded replay**

Redirect pytest output to `/tmp/5194-replay.log`; print only aggregate
disposition and owner tags.

- [ ] **Step 4: Run direct claim-mass tripwires**

Run `test_claim_mass_tripwires.py` directly with the local
provenance-matched release binary. Re-pin loudly if a fixture moved.

- [ ] **Step 5: Run the fresh witness**

Run the new witness against that same local binary with all source/error twins
written under pytest `tmp_path`; print only pass/fail count.

- [ ] **Step 6: Rebase if #5191 merged and replay timeout rows**

If merged, rebuild the exact binary and repeat the single-lane
30→120→300-second timeout measurement. Report any retired rows as resolved by
#5191, not by this implementation.

---

### Task 4: Publish without merging

**Files:**
- Modify only files listed above

**Interfaces:**
- Consumes: committed implementation and receipt counts
- Produces: draft PR on `fatal-corpus-timeout-singleton-residual`

- [ ] **Step 1: Format and inspect scope**

Run Black on changed Python files, `git diff --check`, and inspect
`git status --short --branch`.

- [ ] **Step 2: Commit as T Savo**

Commit the semantic implementation and receipts with author
`T Savo <evilgenius@nefariousplan.com>`.

- [ ] **Step 3: Push and open a draft PR**

Use a non-closing body containing `Part of #5194`, the per-front disposition,
the recognizer name `class_decorators_preserve_identity`, conservation,
discrimination, claim-mass, and witness receipts.

- [ ] **Step 4: Verify live PR state**

Confirm the PR is open, draft, based on `main`, and not merged.
