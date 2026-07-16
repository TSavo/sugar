# Fatal Python Corpus Files Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce every assertion-bearing NumPy/pandas file in an isolated child process, classify every terminal failure without weakening it, rank the live fatal frontier, and publish actionable issue splits.

**Architecture:** A parent census process enumerates the exact NumPy 2.5.1 and pandas 3.0.3 corpus and launches a fresh child for each assertion-bearing file. The child either returns a completed marker or serializes the terminal Python exception; signals, aborts, timeouts, missing child testimony, and transport diagnostics remain parent-observed outcomes. Aggregation groups typed `FactoryPanic` rows by structured owner/observed/requested identity and keeps process-crash, transport, timeout, and bare-exception categories disjoint.

**Tech Stack:** Python 3.14, `subprocess`, Sugar Python lift kit, NumPy 2.5.1, pandas 3.0.3, GitHub CLI.

## Global Constraints

- A fatal file must remain fatal; never emit or count a partial lift report.
- Measurement and triage only; no recognizer, floor, verifier, transport, timeout, or failure-semantics fixes.
- Use the isolated worktree virtualenv and a locally resolved Sugar binary when the shelf misses.
- Branch `recensus-fatal-files-triage`; author `T Savo <evilgenius@nefariousplan.com>`.
- PR and issue bodies say `Part of #4684`; never close/fix #4684; do not gate or merge.

---

### Task 1: Build the fatal-only subprocess instrument

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`
- Test: direct CLI smoke runs against one completing and one panicking file

**Interfaces:**
- Consumes: installed package roots and `lift_file_payload(source, relative_path)`
- Produces: JSON with corpus provenance, terminal category counts, structured FactoryPanic fingerprints, representative files, and per-file terminal rows

- [ ] **Step 1: Add child mode** that reads exactly one corpus file, calls `lift_file_payload`, emits `{"outcome":"completed"}` only after a completed payload exists, and emits structured terminal exception testimony before exiting nonzero for caught Python failures.
- [ ] **Step 2: Add parent mode** that AST-censuses the deterministic corpus, skips files without assertions, invokes one child per assertion-bearing file with a 30-second timeout, and records return code, signal, stdout testimony, and stderr diagnostic.
- [ ] **Step 3: Classify outcomes** into `process-crash-or-overflow`, `factory-construction-panic`, `transport-disconnect`, `timeout-or-hang`, and `bare-exception`, with FactoryPanic sub-fronts keyed by owner, gap kind/locus, observed, and requested.
- [ ] **Step 4: Add deterministic sharding and compact output** so package shards can run concurrently without shared Python lift state.
- [ ] **Step 5: Verify child discrimination** with one known completed file and one known FactoryPanic file; confirm the latter exits nonzero and produces no completed marker.

### Task 2: Run the current-main fatal census

**Files:**
- Create: `docs/python-corpus-fatal-triage-4684-2026-07-16.md`

**Interfaces:**
- Consumes: Task 1 JSON shard outputs
- Produces: ranked category and FactoryPanic sub-front tables with exact arithmetic and representatives

- [ ] **Step 1: Create the isolated editable environment** with NumPy 2.5.1, pandas 3.0.3, and Black 26.5.1.
- [ ] **Step 2: Resolve/build the local Sugar binary** with `bin/sugarbin --profile release`; record the path and source commit without using a mismatched shelf artifact.
- [ ] **Step 3: Run NumPy and deterministic pandas shards**, retaining the child-process return status for all 1,032 assertion-bearing files.
- [ ] **Step 4: Verify arithmetic**: completed plus every fatal category equals assertion-bearing files; shard file totals equal 407 NumPy plus 1,421 pandas; no row belongs to two terminal categories.
- [ ] **Step 5: Write the triage report** with category count, representatives, likely owner, top structured FactoryPanic fronts, and explicit confirmation that crashes/transports were or were not observed.

### Task 3: Dispatch actionable fronts and publish

**Files:**
- Modify only the Task 1 instrument and Task 2 report if verification finds reporting defects

**Interfaces:**
- Consumes: ranked exact triage report
- Produces: available GitHub issues for the largest independent actionable mechanisms, an #4684 triage comment, and a draft measurement PR

- [ ] **Step 1: Search open and closed issues** for each top independent mechanism using owner, observed shape, requested floor, and representative file names.
- [ ] **Step 2: File only non-duplicate actionable sub-fronts** as available issues, preserving loud failure law and linking `Part of #4684`.
- [ ] **Step 3: Verify formatting and instrument CLI**, then commit as T Savo, push `recensus-fatal-files-triage`, and open a draft PR with `Part of #4684` and `DO NOT MERGE`.
- [ ] **Step 4: Post the ranked table to #4684**, link the report/PR/sub-front issues, and verify the live comment and draft PR state.
