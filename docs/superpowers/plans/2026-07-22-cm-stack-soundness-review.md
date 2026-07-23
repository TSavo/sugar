# CM Stack Soundness Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make prerequisite 1 independently publish sealed typed CM declarations, then give prerequisite 2 discriminating phase-order and complete AST boundary floors.

**Architecture:** Move only the typed kit publication boundary and dedicated compiler-feed integration from the stacked resolution branch into the publisher branch. Rebase the resolver stack, replace observational tests with planted regressions, and retain Rust-owned resolution without adding With semantics.

**Tech Stack:** Python 3, pytest, Rust, cargo tests through battleaxe `bin/sugarbin`, GitHub stacked PRs.

## Global Constraints

- No ContractBody, formula atoms, or function-contract minting in the CM publication arm.
- Tree and Sugar construction consume only injected typed refs.
- Heavy Rust verification runs only on battleaxe through `bin/sugarbin`.
- Both PRs remain non-draft and are never self-merged.

---

### Task 1: Restore the prerequisite-1 publication boundary

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_context_manager_contract.py`
- Modify: `implementations/rust/sugar-compiler/src/feed_from_tree.rs`
- Modify: `implementations/rust/sugar-compiler/tests/context_manager_contract_feed.rs`

**Interfaces:**
- Consumes: `ContextManagerContractIrV1`
- Produces: typed kit declaration rows sealed by `graph_from_context_manager_contract_ir`

- [ ] Add a failing test proving the publisher branch exposes the typed declaration through the ordinary kit declaration/compiler feed.
- [ ] Run the focused Python test and observe the missing production door failure.
- [ ] Move the minimal typed publication boundary from prerequisite 2.
- [ ] Run focused Python and battleaxe Rust round-trip/feed tests.
- [ ] Commit and push PR #6072.

### Task 2: Make the RPC order twin discriminating

**Files:**
- Modify: `implementations/rust/sugar-compiler/tests/prove_from_kit.rs`
- Modify: the fixture RPC kit used by that test.

**Interfaces:**
- Consumes: production `fold_kit_to_pool` RPC sequence
- Produces: an exact ordered event receipt

- [ ] Replace the success-only assertion with a failing sequence assertion.
- [ ] Confirm the planted bind-after-enumerate ordering fails.
- [ ] Implement event capture and assert declarations, demands, bind, first semantic enumeration.
- [ ] Run the focused battleaxe test green.

### Task 3: Replace lexical floors with an AST detector

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_cm_construction_boundary.py`
- Create: a focused detector helper beside the test if production reuse is unnecessary.

**Interfaces:**
- Consumes: complete `sugar_source_tree` and Sugar implementation roots
- Produces: deterministic offender rows and R count

- [ ] Write four planted tests for direct, nested-helper, aliased-import, and out-of-selected-file violations and observe the old floor miss them.
- [ ] Implement AST import alias and call-chain recognition over every Python file in both roots.
- [ ] Run all planted tests and the real-tree zero floor.
- [ ] Rebase and push PR #6076.

### Task 4: Verify and hand off

**Files:**
- No production changes.

**Interfaces:**
- Consumes: both final branch heads
- Produces: battleaxe/Python receipts and architect review requests

- [ ] Run focused and broad Python tests.
- [ ] Run focused Rust and compiler checks on battleaxe through `bin/sugarbin`.
- [ ] Confirm #6072 is based on main and #6076 is based on #6072 with no duplicated publication commit.
- [ ] Re-request architect review on both non-draft PRs.
