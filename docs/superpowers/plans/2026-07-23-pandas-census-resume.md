# Pandas Census Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every pandas census result at completion, resume without rerunning durable files, isolate every construction, and reconcile one complete five-floor 1,415-file run.

**Architecture:** A shared checkpoint module owns manifest identity, strict JSONL validation, durable append, resume selection, and row conservation. Each floor retains its own typed classifier and aggregate, but delegates scheduling durability to that module; control/effect gains the same child boundary already used by the other floors.

**Tech Stack:** Python 3.12, subprocess, concurrent futures, append-only JSONL, pytest, battleaxe `bin/bpytest`/`brun`.

## Global Constraints

- The per-file wall bound is at most 30 seconds and is never escalated.
- A panic or backend defect remains a counted typed row; genuine infrastructure bugs remain fatal.
- No row may be fabricated for a file that did not finish.
- All five floors must use one identical non-empty corpus manifest CID.
- The production run stays pinned to commit `c401588017ae93e9b379a34b0a155830fc710ae7`.
- Do not merge the PR.

---

### Task 1: Durable checkpoint contract

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/scripts/pandas_census_checkpoint.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_pandas_census_checkpoint.py`

**Interfaces:**
- Produces: `Checkpoint(floor, files, path)`, `pending_files()`, `append(file, result)`, and `rows()`.
- Enforces: records keyed by `(corpusManifestCid, file)` and strict one-row-per-manifest-file conservation.

- [ ] Write failing tests that load a durable early row after reopening, reject a foreign CID, reject duplicate keys, and reject malformed JSONL.
- [ ] Run `bin/bpytest implementations/python/sugar-lift-py-tests/tests/test_pandas_census_checkpoint.py -q` and confirm failures are caused by the absent module/API.
- [ ] Implement canonical manifest calculation, strict load validation, and append using `flush()` plus `os.fsync()`.
- [ ] Re-run the focused test and confirm all checkpoint contract tests pass.
- [ ] Commit the checkpoint unit as `Persist pandas census rows durably`.

### Task 2: Completion-order resumable scheduler and required twins

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/pandas_census_checkpoint.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_pandas_census_checkpoint.py`

**Interfaces:**
- Produces: `run_pending(checkpoint, worker, workers)` that invokes only absent files and appends each returned typed result immediately in completion order.

- [ ] Write the killed-run twin using a subprocess fixture that records invocations, completes file A, blocks on file B, is killed, then resumes; assert A ran once and all final keys exist.
- [ ] Run the exact twin and confirm it fails because resume scheduling is absent.
- [ ] Implement pending-only submission and `as_completed` append behavior.
- [ ] Run the killed-run twin and confirm it passes.
- [ ] Write the crash-between-good-files twin whose worker returns success, typed native crash, success; assert all three rows persist.
- [ ] Run the twin and confirm its expected pre-implementation failure.
- [ ] Add typed worker-exception handling only for declared child terminal results; let parent/infrastructure exceptions propagate.
- [ ] Run both twins and the full checkpoint test module.
- [ ] Commit as `Resume pandas census from completed files`.

### Task 3: Integrate fatal, silent, native-crash, and timeout floors

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/silent_zero_tolerance.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/native_crash_zero_tolerance.py`
- Modify: `implementations/python/sugar-lift-py-tests/scripts/timeout_zero_tolerance.py`
- Modify: corresponding `tests/test_*zero_tolerance.py` and `tests/test_corpus_fatal_triage.py`

**Interfaces:**
- Consumes: shared checkpoint and completion-order scheduler.
- Produces: `--checkpoint-jsonl PATH` on every floor and final reports aggregated solely from conserved checkpoint rows.

- [ ] Add failing focused tests proving each floor skips a durable row and preserves typed crash/panic/timeout/non-native-red categories.
- [ ] Run the focused modules and confirm the new assertions fail for missing checkpoint integration.
- [ ] Route each parent loop through the shared scheduler while preserving existing child classification.
- [ ] Reject `--file-timeout` values above 30.
- [ ] Re-run the focused modules and confirm green.
- [ ] Commit as `Checkpoint isolated pandas census floors`.

### Task 4: Isolate and checkpoint control/effect

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_recensus_panic_collection.py`
- Create or modify: `implementations/python/sugar-lift-py-tests/tests/test_control_effect_recensus.py`

**Interfaces:**
- Consumes: shared checkpoint scheduler.
- Produces: child JSON testimony sufficient to reconstruct counts, mechanisms, defects, panics, and per-file floor rows; default and maximum timeout 30 seconds.

- [ ] Write failing tests for a planted child signal, ConstructionPanic testimony, backend exception testimony, timeout, and continuation to a later good file.
- [ ] Run the focused tests and confirm they fail against parent-process construction.
- [ ] Add child mode and parent classification, returning full per-file aggregate deltas.
- [ ] Aggregate only checkpoint testimony and emit a floor summary only at complete conservation.
- [ ] Re-run focused control/effect and panic-collection tests.
- [ ] Commit as `Isolate control effect census files`.

### Task 5: Harden reconciliation and verify PR scope

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/reconcile_pandas_floors.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_pandas_floor_summary.py`

**Interfaces:**
- Consumes: five complete native floor summaries.
- Produces: `validated-summary.json` only when floor names, row conservation, non-empty identical manifest CID, and measured states agree.

- [ ] Write failing tests for an incomplete 1,415-file floor, row/file mismatch, and same-CID-but-tampered files.
- [ ] Run the focused reconciler test and confirm failure.
- [ ] Implement strict expected-denominator and cross-floor manifest equality validation without synthesizing missing rows.
- [ ] Run all focused runner/reconciler tests through `bin/bpytest`.
- [ ] Inspect `git diff --check`, changed-file scope, and 30-second bound searches.
- [ ] Commit as `Validate complete pandas floor reconciliation`.

### Task 6: Publish the unmerged PR

**Files:**
- Modify only files already named above if verification exposes a scoped defect.

- [ ] Run the focused Python test set on battleaxe with `bin/bpytest` and retain the receipt.
- [ ] Confirm commit identity, clean status, base SHA, and branch diff.
- [ ] Push `agent/pandas-census-resume` and open a PR describing semantics and exact focused validation.
- [ ] Report the PR number immediately and leave it unmerged.

### Task 7: Commit-pinned five-floor production census

**Files:**
- Write receipts outside tracked source under one battleaxe run directory.

- [ ] Resolve the battleaxe checkout at the pinned implementation commit and record commit/interpreter/corpus provenance.
- [ ] Discover the pandas manifest once, prove it has exactly 1,415 files, and initialize five checkpoints against that CID.
- [ ] Launch the five floors sequentially in detached tmux using the same run directory and 30-second per-file bound.
- [ ] Monitor numeric progress only; after disconnect/reboot rerun the same command against the same checkpoint without changing commit or receipt root.
- [ ] Require 1,415 validated rows on every floor, then run `reconcile_pandas_floors.py` to produce `validated-summary.json`.
- [ ] Read back numeric totals only and report `R_total`, per-class totals, corpus CID, pinned commit, and summary path.
