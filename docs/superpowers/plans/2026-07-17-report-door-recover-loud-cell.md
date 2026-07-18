# Report-Door Loud-Cell Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover per-definition `FactoryPanic` at the default report door as mandatory red evidence while rendering independent definitions.

**Architecture:** Reuse the existing definition-level catch in `audit_lift_file` under a report-only continuation flag. Preserve the diagnostic recovered-audit DTO contract, stamp the poisoned definition span on the existing factory red-row DTO, retain its claims on the mandatory red gate, and make both unresolved factory rows and nonzero gate mass hard CLI failures.

**Tech Stack:** Python 3.14, pytest, typed kit RPC DTOs, Rust `sugar-cli` report renderer.

## Global Constraints

- Never mint ProofIR, a runtime effect, or an empty-success row from a recovered panic.
- A recovered cell is always `status=unresolved`, `verdict=gap`.
- Direct audits remain fail-fast; recovered audits remain diagnostic-only.
- Use the private worktree venv and a locally built Sugar binary.
- No full-corpus sweep.

---

### Task 1: Red discrimination and conservation

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_report_renders_none_arm_red.py`

**Interfaces:**
- Consumes: `lift_file_payload`, `audit_lift_file`, `account_lift_coverage`.
- Produces: regression coverage for report-only recovery and audit fail-fast.

- [ ] Add a clean definition plus an unknown-local `isinstance` definition.
- [ ] Assert current `lift_file_payload` raises `FactoryPanic`; run the focused test and retain the failure.
- [ ] Assert the target behavior: clean assertion fact retained, loud assertion fact absent, one unresolved red row names `UnknownLocal`, its claim trips `silently_unaccounted`, and no effect row exists.
- [ ] Assert direct `audit_lift_file` still raises and recovered audit still returns no ProofIR.

### Task 2: Report-only definition continuation

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/lift_coverage_accounting.py`
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`

**Interfaces:**
- Consumes: existing `gap_from_factory_panic` and `_factory_walk_red_from_gap`.
- Produces: `audit_lift_file(..., recover_report_panics=True)` returning partial report payload plus typed gaps only for `lift_file_payload`.

- [ ] Add a closed report-only continuation flag rejected when combined with recovered-audit mode.
- [ ] Call that mode from `lift_file_payload`.
- [ ] In the existing definition catch, append the typed gap and red row, then continue only for report mode.
- [ ] Stamp the recovered owner span and keep its unconstructed claims on the red gate.
- [ ] Treat unresolved report rows and nonzero silent-gate mass as hard CLI failures.
- [ ] Preserve fail-fast and recovered-audit branches unchanged.
- [ ] Run the focused discrimination and nearby RPC DTO tests green.

### Task 3: Verdict witness and datetime re-shot

**Files:**
- Modify: focused Python/Rust tests only if the existing report verdict harness lacks a suitable entry point.

**Interfaces:**
- Consumes: serialized `factoryAuditSummary.statusCounts.unresolved`.
- Produces: fresh truthful-red / swallowed-green-refuting receipt.

- [ ] Build `sugar-cli` locally in a worktree-private Cargo target directory.
- [ ] Run the focused CLI report witness and confirm the recovered row causes nonzero exit.
- [ ] Run the swallowed/green twin and confirm the witness refutes it.
- [ ] Run the full vendored datetime report and confirm rendering completes with per-cell rows.
- [ ] Run `make test-claim-mass-tripwires` using the private worktree venv and loudly re-pin in this PR only if a pinned fixture advanced.
- [ ] Rebase on current `origin/main`, rerun focused receipts, commit, push, and open a ready non-closing PR with `Part of #5109`.
