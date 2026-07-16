# Universe-Absence Factory Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit a typed Python factory-walk gap for asserted callees with no universe construction route while retaining the completed fact and unchanged verifier refusal.

**Architecture:** A pure post-assertion audit producer classifies completed call-edge demands against already-constructed function contracts, builtin factory claims, bridge contracts, and vendor-proof identities. `lift_rpc` projects only uncovered demands through the existing red factory-walk boundary; it never changes the lift outcome or verifier.

**Tech Stack:** Python 3, `sugar_lift_py_tests`, pytest, pyright, existing kit RPC DTOs.

## Global Constraints

- Never weaken or modify the verifier.
- A missing universe never becomes success.
- Keep completed assertion facts and call edges intact.
- Do not add Base64 or pandas universe recognizers.
- Use an isolated worktree-local environment with Black 26.5.1.

---

### Task 1: Pin the discrimination pair

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/tests/test_universe_coverage_gap.py`

**Interfaces:**
- Consumes: `lift_file_payload(source: str, filename: str) -> LiftReportPayloadDto`
- Produces: assertions for the positive universeless row and negative covered twin.

- [ ] **Step 1: Write the failing positive test**

Assert that `test_vendor_only` retains its `vendor_only(1) == 1` fact and call edge,
and that `factory_walk` contains a red row naming `call:vendor_only`,
`owner=python.factory`, the exact call locus, the four missing routes, and the four
retirement paths.

- [ ] **Step 2: Run the positive test and verify RED**

Run: `pytest -q tests/test_universe_coverage_gap.py::test_universeless_assertion_emits_named_factory_gap`

Expected: FAIL because no universe-absence row exists while the fact and edge do.

- [ ] **Step 3: Write the covered negative test**

Define `covered(value): return value`, assert `covered(1) == 1`, and require no
universe-absence row for `call:covered`.

### Task 2: Construct the additive universe audit

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only/universe_coverage.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py`

**Interfaces:**
- Produces: `universe_coverage_gaps(payload: LiftReportPayloadDto) -> list[FactoryGapInfo]`
- Consumes: completed `payload.ir`, `payload.call_edges`, and `payload.factory_walk`.

- [ ] **Step 1: Implement exact evidence-route classification**

Normalize each asserted call-edge target, match same-lift body contracts by qualified
callee identity, recognize builtin coverage from the selected factory row at the call
locus, and accept explicit `targetContract`/`targetContractCid` or `targetProofCid`
testimony. Return no row when any route exists.

- [ ] **Step 2: Construct typed absence diagnostics**

Build `FactoryGapInfo(owner="python.factory", gap_kind=GapKind.SUGAR,
gap_locus=GapLocus.CONSTRUCTION, ...)` from the edge target and locus. Deduplicate by
callee and source locus without changing call-edge order.

- [ ] **Step 3: Append through the existing ledger boundary**

In `audit_lift_file`, after all completed definitions are projected, convert each typed
diagnostic to the existing audit-only gap representation and append its red
`FactoryWalkRedRowDto`. Do not raise and do not remove IR.

- [ ] **Step 4: Run the discrimination pair and verify GREEN**

Run: `pytest -q tests/test_universe_coverage_gap.py`

Expected: both arms pass; positive retains fact plus named gap, negative has no gap.

### Task 3: Verify existing ledgers and report receipt

**Files:**
- Modify only if an exact current DTO spelling requires test alignment.

**Interfaces:**
- Consumes: existing factory gap, walk, assertion-axis, and report tests.
- Produces: focused green receipts and a small lift-report receipt.

- [ ] **Step 1: Run existing gap-ledger tests**

Run: `pytest -q tests/test_factory_gap_info.py tests/test_factory_walk_lane.py tests/test_factory_walk_row_dto.py tests/test_report_renders_none_arm_red.py tests/test_assertion_axis.py`

Expected: all pass unchanged.

- [ ] **Step 2: Run the type and format gates**

Run the repository's focused pyright ratchet and Black 26.5.1 check over modified files.

- [ ] **Step 3: Produce the small vendor receipt**

Lift the positive and covered fixtures through `lift_file_payload`; record that the
positive report retains its fact and names the universe-absence row, while the covered
twin emits no such row.

- [ ] **Step 4: Commit and publish**

Commit as `T Savo <evilgenius@nefariousplan.com>`, push
`universe-absence-factory-gap`, and open a draft PR with `Part of #3896` and
`Part of #3864`. Do not gate or merge.
