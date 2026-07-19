# Pandas Timeout Residual Disposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every one of the 66 pandas files left as timeouts after #5321 a durable, current-main terminal disposition without changing the product bound or semantics.

**Architecture:** Replay the exact conserved manifest through the repository's ordinary `corpus_fatal_triage.py` product child on battleaxe, with an external 30-second bound and optional heartbeat tracing disabled. Convert its file-backed testimony into a checked-in ledger whose validator requires exact manifest identity, one terminal per file, conservation, and zero silence. A production performance change is permitted only if the replay proves a live shared timeout mechanism; otherwise the PR records the measured completed and loud dispositions.

**Tech Stack:** CPython 3.12.3, `bin/brun`, JSON, pytest.

## Global Constraints

- Run the lift replay through `brun`/`bcargo` only.
- Keep the per-file bound at 30 seconds.
- Never skip, suppress, raise the bound, or convert a timeout to RuntimeEffect.
- Cache only immutable successfully constructed results keyed by content identity.
- Do not handle the historical bare-exception rows owned by #5322.
- Preserve `silent=0`.

---

### Task 1: Current-main 66-file replay

**Files:**
- Read: `docs/ledgers/pandas-timeout-shared-mechanism-5306.json`
- Produce remotely: `target/pandas-timeout-disposition-5330/current-main.json`

**Interfaces:**
- Consumes: the 66 rows whose #5321 disposition is `timeout-or-hang`
- Produces: one bounded terminal testimony per input file

- [ ] **Step 1: Extract the exact 66-file manifest**

Run:

```bash
jq -r '.files[] | select(.disposition == "timeout-or-hang") | .file' \
  docs/ledgers/pandas-timeout-shared-mechanism-5306.json \
  > target/pandas-timeout-disposition-5330/files.txt
```

Expected: exactly 66 unique paths.

- [ ] **Step 2: Replay through the bounded child instrument**

Run on battleaxe through `bin/brun`, with Python 3.12.3:

```bash
timeout 30s env SUGAR_ENGINE_PROGRESS=0 SUGAR_ENGINE_TRACE_EVENTS=0 \
  python implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py \
  --child-file "$pandas_root/$relative_path" \
  --child-rel "pandas/$relative_path"
```

Run once per manifest row and retain each child result file-backed. Expected: 66 terminal rows; every timeout remains explicitly named.

### Task 2: Tooth-bearing disposition ledger

**Files:**
- Create: `docs/ledgers/pandas-timeout-residual-disposition-5330.json`
- Create: `tests/test_pandas_timeout_residual_disposition.py`

**Interfaces:**
- Consumes: Task 1 testimony and the exact #5321 residual manifest
- Produces: a durable ledger and a conservation test

- [ ] **Step 1: Write the failing ledger test**

The test must require:

```python
assert len(expected_files) == 66
assert set(actual_files) == expected_files
assert sum(disposition_counts.values()) == 66
assert disposition_counts["silent"] == 0
assert disposition_counts["timeout-second-mechanism"] == 0
assert disposition_counts["timeout-irreducible"] == 0
```

It must also reject unknown dispositions and duplicate paths.

- [ ] **Step 2: Verify the test is red**

Run:

```bash
python -m pytest -q tests/test_pandas_timeout_residual_disposition.py
```

Expected: failure because the disposition ledger does not yet exist.

- [ ] **Step 3: Add the measured ledger**

Populate all 66 rows from Task 1. Store only file identity, terminal disposition, and typed-panic owner/kind fields; do not copy vendor source text.

- [ ] **Step 4: Verify the focused test is green**

Run the same pytest command. Expected: pass with exact conservation.

### Task 3: Publish the measured disposition

**Files:**
- Modify only if Task 1 proves a live shared timeout mechanism: the mechanism's owning implementation and focused regression test

**Interfaces:**
- Consumes: the live timeout subset from Task 1
- Produces: either a lawful mechanism drain or an explicit zero-live-mechanism ledger

- [ ] **Step 1: Decide from testimony**

If current timeout count is zero, make no production change. If nonzero, cluster uniform stack samples and implement only a shared mechanism supported by those samples.

- [ ] **Step 2: Verify**

Run the focused ledger test and re-read the generated conservation totals.

- [ ] **Step 3: Commit and publish**

Commit as `Record pandas timeout residual dispositions`, push `pandas-timeout-disposition`, and open a non-closing PR whose body says `Part of #5330`.
