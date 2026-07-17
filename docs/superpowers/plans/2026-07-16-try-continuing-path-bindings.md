# Try Continuing-Path Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construct `TemporalContext` bindings from the reduced paths of `try`/`except` so only bindings guaranteed on every continuing path reach the enclosing continuation.

**Architecture:** `TrySugar` reduces each path with terminal scope testimony, classifies continuation through the reduced outcome's `follow()` result, and returns joined bindings as ordinary scope effects. A binding missing from any continuing path remains absent; runtime-dependent joins remain loud.

**Tech Stack:** Python 3.14, pytest, Sugar Python lift kit, NumPy 2.5.1, pandas 3.0.3.

## Global Constraints

- Never preseed, infer, or fabricate a temporal binding.
- Never catch/suppress `FactoryPanic`, emit a partial report, or weaken the verifier.
- Join only actual reduced continuing-path scopes.
- Runtime-dependent or unguardable continuation remains a named typed gap/effect.
- Existing try/except tests remain unchanged.
- Branch `temporal-context-bindings`; author `T Savo <evilgenius@nefariousplan.com>`.
- PR body says `Part of #4696`, never closes/fixes, and says `DO NOT MERGE`.

---

### Task 1: Pin continuing-path scope semantics red

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_try_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_try_sat_unsat.py`

**Interfaces:**
- Consumes: production `build_sugar_body`, `lift_file_payload`, and existing try witness helpers.
- Produces: red tests for guaranteed binding propagation, missing-path loudness, and truthful/lying discrimination.

- [ ] **Step 1: Add a guaranteed-binding unit test** whose try body assigns `result`, whose handler returns, and whose continuation returns `result`; assert current reduction raises the named `TemporalContext` gap before implementation.
- [ ] **Step 2: Run the focused test** and verify RED is exactly `owner=TemporalContext observed=result requested=value`.
- [ ] **Step 3: Add a missing-path bad control** whose handler falls through without assigning `result`; assert that this control continues to raise the same named gap after the future implementation.
- [ ] **Step 4: Add truthful/lying lift twins** for a guaranteed binding, asserting the truthful twin's fact is emitted and the lying twin differs/refutes through the existing production witness surface.
- [ ] **Step 5: Run the new slice** and retain the expected pre-implementation red receipt.

### Task 2: Construct the reduced continuing-path join

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_try_sugar.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_try_sat_unsat.py`

**Interfaces:**
- Consumes: `BlockSugar.reduce_with_scope(ctx) -> (BlockValue, ReduceContext)`, `Outcome.follow()`, handler guards, and `ScopeRebind`.
- Produces: a `TrySugar` outcome whose contribution includes scope effects for bindings present on every reduced path that can continue.

- [ ] **Step 1: Add a private reduced-path record** in `try_sugar.py` carrying `entries`, terminal `scope`, path guard, and the reduced `FollowStep` continuation decision.
- [ ] **Step 2: Reduce the normal body and handlers once** with `reduce_with_scope`, preserving existing guarded report contributions and handler-scope construction.
- [ ] **Step 3: Select continuing paths from reduced outcomes** using `follow()`; do not inspect AST node kinds.
- [ ] **Step 4: Join bindings across all continuing scopes** by intersection against the incoming context. Emit `ScopeRebind` only for bindings testified on every continuing path; when one path alone continues, replay its constructed bindings directly.
- [ ] **Step 5: Keep unguardable differing bindings loud** by producing the existing typed construction gap/effect rather than choosing a value.
- [ ] **Step 6: Run the focused tests** and verify the guaranteed-binding and truthful/lying controls turn green while the missing-path bad control remains loudly red.
- [ ] **Step 7: Run all existing try slices unchanged**: `test_try_sugar.py`, `test_try_sat_unsat.py`, `test_try_fallback_owner.py`, and `test_residual_try_multi_and_to_term.py`.
- [ ] **Step 8: Commit the semantic mechanism** as T Savo.

### Task 3: Verify the production representative

**Files:**
- No production changes unless the focused receipt exposes a mechanism defect.

**Interfaces:**
- Consumes: installed pandas `io/parsers/base_parser.py` and `corpus_fatal_triage.py --child-file`.
- Produces: an EXIT 0 completed payload with a nonzero real fact count, or a different named loud frontier if a later independent construction gap is reached.

- [ ] **Step 1: Run the exact current-main representative** from the private venv.
- [ ] **Step 2: Confirm the old `result` TemporalContext panic is retired** and record exit, fact count, and any next independent loud frontier.
- [ ] **Step 3: If a new independent frontier appears**, stop widening this mechanism and report it separately; do not relabel it as a failed binding fix.

### Task 4: Measure the #4696 Delta and publish

**Files:**
- No source files; publish the measured Delta in the PR body and #4696 comment.

**Interfaces:**
- Consumes: `corpus_fatal_triage.py` JSON outputs before/after and structured FactoryPanic fingerprints.
- Produces: exact remaining `TemporalContext` owner count, exact retired file count from baseline 241, and representative transitions.

- [ ] **Step 1: Run NumPy plus deterministic pandas shards** with fresh child isolation and persisted JSON output.
- [ ] **Step 2: Serially adjudicate every timeout** before assigning a product category.
- [ ] **Step 3: Aggregate `TemporalContext` first-terminal owner rows** and calculate `Delta = current - 241`; persist the complete exact retired-file list in the measurement output and summarize representatives in the PR.
- [ ] **Step 4: Run Black and focused Python type/test hygiene** without launching broad gate suites.
- [ ] **Step 5: Commit the measurement/report**, push `temporal-context-bindings`, and open a draft PR with `Part of #4696` and `DO NOT MERGE`.
- [ ] **Step 6: Comment the exact Delta and receipts on #4696**, verify the live PR is draft/open/unmerged, and preserve the worktree.
