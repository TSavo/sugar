# Pandas Timeout Deferred Function Body Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the shared pandas timeout mechanism by preventing module
seeding and install-source resolution from recursively factory-building
function bodies before a callable is demanded.

**Architecture:** `StatementFunctionDefSugar` continues to construct
definition-time evidence eagerly: decorators, positional defaults, keyword-only
defaults, signature, and lexical module context. It stores the recognized
function-body source fragments without factory-building their descendants.
`_construct_callable` wraps those fragments in the existing
`SequentialDigBody` and `ContextualizedDigBody`, so ordinary factory
construction occurs when call substitution demands the body. The same opt-in
is used by `_construct_install_source_value`, which profiling identified as the
dominant recursive construction seam.

**Tech Stack:** CPython 3.12.3, pytest, Sugar Python factory/SugarBody,
`SequentialDigBody`, battleaxe `bcargo`.

## Global Constraints

- Keep the per-file timeout at 30 seconds.
- Never skip, xfail, suppress, emit empty success, or convert a timeout into a
  `RuntimeEffect`.
- Decorators and defaults remain eager because Python evaluates them when the
  definition executes.
- Unsupported body construction remains an honorable `FactoryPanic` when the
  callable body is demanded.
- Raw vendor source and witness bodies remain file-backed.
- Author commits as `T Savo <evilgenius@nefariousplan.com>`.
- PR is non-closing, says `Part of #5306`, and is not self-merged.

---

### Task 1: Pin deferred body construction

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_statement_function_def_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/statement_function_def_sugar.py`

**Interfaces:**
- Consumes: `SourceFragment.function_body()` and the existing
  `SequentialDigBody(statements, fn_site, contextmanager_yield)` constructor.
- Produces: `StatementFunctionDefSugar.body_statements`, a tuple of recognized
  source fragments built into a contextualized body only in
  `_construct_callable`.

- [x] **Step 1: Write the failing discrimination test**

Add a test that monkeypatches `FactoryBuildContext.build_body`, constructs a
statement-role function with many unsupported body expressions, and asserts
that `StatementFunctionDefSugar.new(...).desugar(...)` does not factory-build
the function-body block or descendants. Assert that the returned
`FunctionCallable.body` exists, then demand it and confirm the unsupported
shape reaches `FactoryPanic`.

- [x] **Step 2: Run the discrimination test red**

Run:

```bash
.venv312/bin/pytest -q implementations/python/sugar-lift-py-tests/tests/test_statement_function_def_sugar.py -k deferred_body
```

Expected: failure because current `new()` calls
`ctx.build_body(site.function_body_block(), SugarRole.STATEMENT)`.

- [x] **Step 3: Store recognized body fragments without eager construction**

Replace the eager `body: SugarBody` field with a tuple of the fragments returned
by `site.function_body()`. In `_construct_callable`, construct the existing
`SequentialDigBody` directly from that tuple and contextualize it with
`module_context_for`. Keep decorator/default reduction unchanged. Remove the
body from `walk_children`; it becomes a child only through the demanded
`FunctionCallable.body`.

- [x] **Step 4: Run focused tests green**

Run:

```bash
.venv312/bin/pytest -q \
  implementations/python/sugar-lift-py-tests/tests/test_statement_function_def_sugar.py \
  implementations/python/sugar-lift-py-tests/tests/test_statement_function_module_import_context.py
```

Expected: all tests pass, including eager decorator/default behavior and loud
unsupported demanded bodies.

### Task 2: Measure the conserved timeout delta

**Files:**
- Create: `docs/ledgers/pandas-timeout-shared-mechanism-5306.json`

**Interfaces:**
- Consumes: the exact 130-file list from #5233 and current-main
  `corpus_fatal_triage.py --child-file`.
- Produces: a per-file category ledger and aggregate conservation vector.

- [x] **Step 1: Replay named representatives at 30 seconds**

Run the current-main baseline and patched branch for representative core,
indexing, series, I/O, and window files. Record completed, named
`FactoryPanic`, timeout, bare exception, and crash.

- [x] **Step 2: Replay all 130 files at 30 seconds**

Use sixteen isolated child processes, never a wider timeout. Store each
file/category row and assert:

```text
completed + factory_panic + timeout + bare + crash = 130
silent = 0
```

- [x] **Step 3: Record the ledger**

Check in a compact JSON ledger with pin, Python/package versions, before/after
counts, per-file dispositions, and the shared-mechanism profile summary. Do not
embed vendor source.

### Task 3: Verify soundness floors and publish

**Files:**
- Modify only if required by existing formatting: files from Tasks 1–2.

**Interfaces:**
- Consumes: focused tests, witness harness, eight-axis construction floors,
  claim-mass tripwire.
- Produces: commit and non-closing PR for #5306.

- [ ] **Step 1: Run fresh witness and wrong twin**

Use a source-file-backed truthful/lying pair whose callable body is deferred;
truthful must be SAT and lying UNSAT. An unsupported demanded body must remain
a `FactoryPanic`.

- [ ] **Step 2: Run floors and claim-mass**

Run the repository’s full eight-axis Python sole-construction floor gate and
the direct pytest claim-mass tripwire with the provenance-matched local kit and
binary.

- [ ] **Step 3: Build and verify through battleaxe**

Build the commit-stamped release binary with `bcargo`/battleaxe and verify the
branch commit provenance before the final witness and cohort replay.

- [ ] **Step 4: Commit and open the PR**

Commit with author `T Savo <evilgenius@nefariousplan.com>`, push, and open a
ready non-closing PR whose body says `Part of #5306`. Do not merge it.
