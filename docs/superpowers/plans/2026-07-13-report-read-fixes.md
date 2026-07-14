# Report Read Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the visual lift report identify its invocation and inputs, show rewrite testimony, label module assertions once, and render enumeration-demanded implication nodes as a complete implication/debt ledger.

**Architecture:** `LiftSourceReport` carries immutable report context captured at the CLI face and implication nodes returned by the same recursive enumeration walk that supplies the rest of the report. `sugar.enumerate(level=implications, at=<call-site memento>)` is the sole work-driving door: one demand resolves and discharges one edge or returns one named debt. Existing source mementos provide file CIDs and dig testimony; no renderer performs lifting or linking.

**Tech Stack:** Rust, serde JSON, `sugar-linker`, focused `sugar-cli` unit tests, battleaxe release mint.

## Global Constraints

- Part of #4424, #4425, #4426, and #4427. Never closes or fixes.
- Author T Savo <evilgenius@nefariousplan.com>.
- Do not gate on broad suites and do not merge.
- Enumeration demand is the only work driver; any reused `link()` algebra operates on one demanded edge only.
- Implication census count equals rendered implication-ledger rows.

---

### Task 1: Report prologue

**Files:**
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`
- Test: `implementations/rust/sugar-cli/src/cmd_lift.rs`

**Interfaces:**
- Consumes: CLI invocation, resolved workspace root, source mementos, plan atoms.
- Produces: `ReportInvocation` and `render_report_prologue`.

- [ ] Add a focused test requiring tool version and binary CID, execution directory, argv, workspace root, every source file/CID, substrate commit, timestamp, LINK state, and same-binary annotation.
- [ ] Run the exact test and observe the missing-prologue failure.
- [ ] Capture context once at the command face and render it before the component plan.
- [ ] Re-run the exact test green.

### Task 2: Dig testimony and module label

**Files:**
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`
- Test: `implementations/rust/sugar-cli/src/cmd_lift.rs`

**Interfaces:**
- Consumes: contract source warrants and source-memento resolutions already present in `LiftSourceReport`.
- Produces: `via ... @ file:line warrant=<cid>` rows and one non-redundant module assertion label.

- [ ] Add one red test for a dug assertion and one red discrimination test for the module-level label.
- [ ] Render warrant-backed rewrite steps between stated source and FOL.
- [ ] Render module assertions without both `(module level)` and `<module>`.
- [ ] Re-run both exact tests green.

### Task 3: Enumeration-driven implication ledger

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`
- Test: focused Python enumeration test and `implementations/rust/sugar-cli/src/cmd_lift.rs`

**Interfaces:**
- Consumes: one call-site memento supplied as `at` to `sugar.enumerate(level=implications)`.
- Produces: one implication node containing edge, obligation, and discharged/unsatisfied/unjoined status with a named reason.

- [ ] Add red enumeration fixtures for one resolvable intra-file call-site key and one dangling call-site key.
- [ ] Assert LINK ran, one obligation row is discharged, one named debt carries the linker reason, and census implications equals ledger row count.
- [ ] Implement the `implications` enumeration leaf so each request computes only the demanded call site, keyed by its memento; no batch collection exists.
- [ ] Extend the CLI report's existing recursive enumeration appetite to demand every call site's implication child and preserve those returned nodes.
- [ ] Render `implication ledger:` rows from that transcript and derive census counts from the same rows.
- [ ] Re-run the exact fixture green.

### Task 4: Ship and focused composed receipt

**Files:**
- Modify: only formatter output in files above.

**Interfaces:**
- Consumes: focused green tests and completed branch.
- Produces: pushed `report-read-fixes` PR plus datetime receipt.

- [ ] Run the pinned Rust formatter and pinned Python black environment.
- [ ] Commit with T Savo authorship, push, and open the PR with `Part of` references.
- [ ] Build and run one detached battleaxe datetime visual mint.
- [ ] Add `EXIT=0` and the new census line to the PR body without waiting on broader CI.
