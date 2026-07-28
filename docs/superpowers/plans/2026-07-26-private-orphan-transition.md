# Private Orphan Transition Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build late telemetry that reports surviving private Python definitions whose last package reference disappeared between two Git trees.

**Architecture:** A focused Python audit parses package-owned source from two Git revisions, indexes private module-level definitions and syntax-authenticated references, and compares the indexes for referenced-before to zero-after transitions. A CLI renders exact definition and lost-reference locations; focused synthetic and historical twins exercise the real artifact.

**Tech Stack:** Python 3 standard library (`ast`, `argparse`, `dataclasses`, `pathlib`, `subprocess`) and pytest.

## Global Constraints

- Base is exactly `b7feb76b8`.
- The detector is late telemetry and must not be wired into CI.
- No handwritten symbol whitelist and no vendor arm.
- Count references through Python syntax, never grep/text occurrence counts.
- Run only focused local tests; use `PYTHONUNBUFFERED=1` because `bin/bpytest` rejects `-u`.
- Capture exit status inline, never after a pipe.

---

### Task 1: Transition index and comparison

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/scripts/private_orphan_transition.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_private_orphan_transition.py`

**Interfaces:**
- Consumes: two Git revisions or two in-memory package trees.
- Produces: immutable definition, reference-site, and orphan-transition records plus `compare_trees(before, after)`.

- [ ] **Step 1: Write failing synthetic tests for surviving-helper loss, helper-plus-caller deletion, export/registration, import/re-export, exact lost sites, and a second helper.**
- [ ] **Step 2: Run the focused pytest file and verify failures are caused by the missing audit module.**
- [ ] **Step 3: Implement AST definition/reference indexing and transition comparison without symbol acknowledgements.**
- [ ] **Step 4: Run the focused file and verify all synthetic cases pass.**

### Task 2: Git-backed historical twin and CLI

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/scripts/private_orphan_transition.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_private_orphan_transition.py`

**Interfaces:**
- Consumes: `--before`, `--after`, and repository path.
- Produces: exit 0 for no transitions; exit 1 with definition and lost-reference sites for findings.

- [ ] **Step 1: Add failing subprocess tests for current-main green and `b7feb76b8` to `b273c4d05` red naming `_has_non_higher_order_return`.**
- [ ] **Step 2: Run the historical tests and verify the missing CLI behavior is the reason for failure.**
- [ ] **Step 3: Implement Git tree loading, package discovery, deterministic rendering, and exit status.**
- [ ] **Step 4: Run the complete focused test file and verify every acceptance case passes.**

### Task 3: Real-history population and shipment decision

**Files:**
- Modify only if test-discovered defects require it: audit script and focused test file.

**Interfaces:**
- Consumes: recent first-parent pairs ending at `b7feb76b8`.
- Produces: measured transition population with exact classifications.

- [ ] **Step 1: Run the audit over recent real first-parent history without output piping and record each transition.**
- [ ] **Step 2: Classify every finding from source evidence; if the population is not low and explainable, bank the negative result and stop.**
- [ ] **Step 3: If shippable, run fresh focused tests and the truthful/lying CLI twins.**
- [ ] **Step 4: Review diff and status for scope, no CI wiring, no whitelist, and no vendor arm.**
- [ ] **Step 5: Commit as `T Savo <evilgenius@nefariousplan.com>`, push, and open an unmerged PR.**
