# Kit Provenance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Testify to the Python kit's imported source identity and refuse split-pipeline report mints before output emission.

**Architecture:** Python computes provenance over the packages it actually imports and places typed testimony in `initialize`. Rust carries that testimony through the lift session, compares it with the compile-time binary commit at the `cmd_lift` boundary, and renders it in matched report prologues.

**Tech Stack:** Python 3.14, pytest, Blake3-512 canonicalizer, Rust, serde, Cargo tests, battleaxe execution helpers.

## Global Constraints

- Work only in `.worktrees/kit-provenance-gate` from `origin/main`.
- Use an isolated editable environment and pin Black 26.5.1.
- The mismatch line is `refusing to mint from a split pipeline: kit @A != binary @B`.
- Mismatch exits nonzero and emits no partial report.
- Dirty matched source is annotated but does not refuse.
- Do not gate. Do not merge.
- PR body contains `Part of #4577` and `Part of #4424` and never closes or fixes either issue.

---

### Task 1: Python source testimony

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_provenance.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_source_provenance.py`

**Interfaces:**
- Produces: `kit_source_provenance() -> dict[str, object]` with `identity`, `kind`, and `dirty`.
- Consumes: imported package `__file__` paths and the existing canonicalizer.

- [ ] Write tests using temporary Git repositories and non-Git package trees.
- [ ] Run the focused pytest file and record the expected missing-module red.
- [ ] Implement deterministic Git/CID testimony and add it to `_handle_initialize`.
- [ ] Re-run the focused pytest file and record green.
- [ ] Commit the independently testable Python testimony.

### Task 2: Preserve testimony through Rust transport

**Files:**
- Modify: `implementations/rust/sugar-compiler/src/kit.rs`
- Modify: `implementations/rust/sugar-cli/src/lift_plugin.rs`
- Test: crate-local tests in the same modules.

**Interfaces:**
- Produces: typed kit source provenance on `LiftPluginSession`.
- Consumes: the kit's actual `initialize_response`; never recomputes Python paths.

- [ ] Write a failing transport/session test proving initialize provenance is lost today.
- [ ] Run the focused Cargo test and record red.
- [ ] Preserve initialize metadata through `Kit::lift` and `LiftPluginSession`.
- [ ] Re-run the focused Cargo test and record green.
- [ ] Commit the independently testable transport change.

### Task 3: Gate and prologue

**Files:**
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`
- Test: crate-local `cmd_lift` tests and, if needed, a focused CLI integration test.

**Interfaces:**
- Consumes: typed kit provenance and `env!("SUGAR_BUILD_GIT_HEAD")`.
- Produces: early exact refusal or a `kit source:` prologue line.

- [ ] Write mismatch, matched, dirty, and no-output failing tests.
- [ ] Run focused Cargo tests and record red.
- [ ] Add comparison before report/proof/render/write work and extend `ReportInvocation`.
- [ ] Re-run focused Cargo tests and record green.
- [ ] Commit the gate and prologue behavior.

### Task 4: Focused and real receipts

**Files:**
- Modify only if a receipt exposes a defect in Tasks 1-3.

**Interfaces:**
- Consumes: the branch binary and isolated editable Python kit.
- Produces: exact split, matched, embedded-commit, and battleaxe datetime receipts.

- [ ] Create the worktree-local virtual environment, editable-install both Python packages, and install `black==26.5.1`.
- [ ] Run focused Python and Rust tests plus formatting.
- [ ] Build release and prove `sugar version --json` reports the branch commit, not `unknown`.
- [ ] Run binary-at-A/kit-at-B and assert line one, both commits, nonzero exit, and absent report.
- [ ] Run binary-at-A/kit-at-A and assert matched prologue rendering.
- [ ] Run the real datetime mint on battleaxe and capture equal provenance lines with exit zero.
- [ ] Commit any receipt-driven corrections, push, and open the non-closing PR without merging.
