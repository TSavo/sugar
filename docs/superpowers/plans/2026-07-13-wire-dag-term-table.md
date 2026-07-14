# Wire DAG Term Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Python's content-addressed term DAG across JSON-RPC so Rust never reconstructs or inventories an expanded term tree.

**Architecture:** An `ir-document` carries one `termTable` map keyed by the existing semantic term CID. Each table node contains scalar term data and immediate child `term-ref` CIDs. Formula term positions contain `term-ref` objects. Rust validates every key by resolving the node graph, interns decoded terms as shared `Arc` values, and gives minting and reporting one lookup-backed representation.

**Tech Stack:** Python dataclasses and canonicalizer, JSON-RPC, Rust serde/serde_json, `Arc`, sugar-canonicalizer, tracing.

## Global Constraints

- Reader and writer flip together, with no compatibility shell.
- Term CIDs are unchanged and remain the keys.
- Invalid, missing, cyclic, or CID-mismatched table entries fail loudly.
- Symbol-kind testimony remains a payload sidecar and never enters term identity.
- No broad gate delays implementation.

---

### Task 1: Python term-table writer

**Files:**
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/ir.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/body_universe_dto.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/lift_report_payload_dto.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_ir_term_interning.py`

**Interfaces:**
- Produces: `TermTableBuilder.reference(term) -> dict[str, str]`, `TermTableBuilder.formula(formula) -> dict[str, Any]`, and payload `termTable`.

- [ ] Write a failing test asserting repeated nested terms produce one table row per semantic CID and formula positions contain only `term-ref` objects.
- [ ] Run the focused pytest and confirm the old inline tree fails the assertion.
- [ ] Implement bottom-up CID calculation over the existing canonical expanded term bytes, cache by immutable `Term`, and emit ref-shaped nodes.
- [ ] Flip `LiftReportPayloadDto.to_rpc` and `BodyUniverseDto` to the builder. Remove inline term emission from this wire door.
- [ ] Run the focused writer tests and CID-parity test.

### Task 2: Rust term-table decoder

**Files:**
- Modify: `implementations/rust/sugar-compiler/src/kit_path/lift_plugin.rs`
- Modify: `implementations/rust/sugar-cli/src/lift_plugin.rs`
- Test: `implementations/rust/sugar-compiler/tests/lift_term_table.rs`

**Interfaces:**
- Consumes: payload `termTable` and `{kind:"term-ref",cid}`.
- Produces: a validated shared term pool keyed by CID, attached to the lift response projection.

- [ ] Write failing tests for shared pointer identity, missing CID, cycle, and key/content mismatch.
- [ ] Decode each table row once into an `Arc` node and validate its semantic expanded CID.
- [ ] Make raw unresolved term refs unavailable outside the transport projection.
- [ ] Run the focused Rust decoder tests.

### Task 3: Mint and report consumers

**Files:**
- Modify: `implementations/rust/sugar-cli/src/cmd_mint.rs`
- Modify: `implementations/rust/sugar-cli/src/cmd_lift.rs`

**Interfaces:**
- Consumes: the validated shared term pool.
- Produces: canonical mint input and visual output without expanding shared children.

- [ ] Write a failing nested-tower test proving mint and render consumers observe one shared child identity.
- [ ] Route canonical mint conversion through the shared nodes.
- [ ] Route formula rendering and inventory through shared nodes and retain the existing symbol-kind table.
- [ ] Run the nested DAG regression and the unstamped-symbol discrimination test.

### Task 4: Protocol and receipts

**Files:**
- Modify: `protocol/specs/2026-07-08-enumeration-protocol.md`

- [ ] Document `termTable`, `term-ref`, unchanged semantic CID keys, mandatory validation, and the absence of an inline-tree compatibility arm.
- [ ] Compare datetime visual output bytes before and after.
- [ ] Record universe 32/69 timing, payload byte delta, and term CID parity.
- [ ] Run the focused corpus-vector comparison named by #4406.
- [ ] Commit as T Savo, push #4388, and update its body with exact receipts.
