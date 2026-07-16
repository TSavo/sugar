# Forall Inactive Accounting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve cfg-inactive nested forall accounting without weakening forall completeness.

**Architecture:** Extend completed constraint payloads with nested inactive reasons. The forall partitions collector skips by disposition, completes only when every skip is inactive and active claims match the active source count, and the outer emitter records those reasons.

**Tech Stack:** Rust, syn, sugar-lift-rust-tests, Cargo tests, battleaxe coretests telemetry.

## Global Constraints

- Keep `forall_gap` unchanged.
- Never count inactive assertions as discharged propositions.
- Never permit ambiguous or unclassified skips to complete.
- Do not merge or gate on broad CI.

---

### Task 1: Pin mixed active/inactive forall accounting

**Files:**
- Modify: `implementations/rust/sugar-lift-rust-tests/src/lib.rs`
- Modify: `implementations/rust/sugar-lift-rust-tests/src/sugar/forall.rs`

- [ ] Add a regression expecting two lifted claims plus one inactive reason.
- [ ] Add a regression expecting an ambiguous nested cfg to retain the forall panic.
- [ ] Run both tests and confirm the mixed test fails at `forall.rs:769` before production changes.
- [ ] Add typed nested reasons to completed constraints and propagate them at emit boundaries.
- [ ] Partition forall skips so only `Disposition::Inactive` participates in a completed result.
- [ ] Run the focused tests green and format the Rust workspace.

### Task 2: Measure the next coretests frontier

**Files:**
- Modify only if the exact invariant snapshot legitimately changes: `implementations/rust/coretests-invariants.json`

- [ ] Run `coretests-invariants` on battleaxe from the branch.
- [ ] Confirm no panic at `forall.rs:769` and no procedural-macro or primitive-int regression.
- [ ] If another hard invariant appears, search for an existing issue and file an available downstream frontier if absent.
- [ ] Commit as T Savo, push `fix-coretests-forall-panic`, and open a draft PR whose body says `Part of #4693` without closing language.
