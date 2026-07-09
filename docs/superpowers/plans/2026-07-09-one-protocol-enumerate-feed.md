# ONE Protocol: Enumerate Completeness + Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sugar.enumerate` drive the same factory semantics the old batch lift drove, then fold those nodes into `ProofGraph` via `feed` so solve has one construction: walk → feed → solve.

**Architecture:** Two stacked campaigns on one branch series. **Campaign A** closes the enumerate surface against the old drive (universes, call identity, non-1:1 assertions). **Campaign B** turns tree nodes into `ProofGraph` fragments and folds them with `feed(+speaker)`. Neither campaign invents a second lifter: Python still uses `lift_source` / `build_node`; Rust still uses the existing membrane.

**Tech Stack:** Rust (`sugar-compiler`, `sugar-proof-envelope`, `sugar-verifier`), Python kit (`sugar_lift_py_tests.lift_rpc`, factory), existing NDJSON JSON-RPC, bcargo / `cargo test -p sugar-compiler`.

**Worktree:** `/Users/tsavo/sugar/.worktrees/one-protocol-3809` on branch `one-protocol-3809` (from `origin/main` @ post-#3894).

**Related issues:** #3809 (epic), #3867 (enumerate completeness), #3865/#3864 (pandas universe), #3822 (one solve), #3859/#3891 (solve_project landed), #3896 (universe-absence as gap).

## Global Constraints

- IDD: every seam starts with a **red instrument** that names current `R`, stays red while debt remains, and green only when the replacement shape is live.
- No second transport: enumeration reuses the Kit stdio membrane (`KitConn` / spawn `--rpc`).
- No `serde_json::Value` in new public verb signatures on the tree/`ProofGraph` path (wire decode at edges only).
- Annotate-not-block on production `solve_project` stays until #3893 (exit-code law) — do not silently change exit codes.
- Byte-identical report/verdict floor: labels may only get more correct.
- Gaps are nodes: never silent empty when the kit has a reason.
- Prefer `.worktrees/` isolation; do not dirty the user's main checkout.
- Gate with the smallest test first (`cargo test -p sugar-compiler …`), then widen.

## File Map

| Path | Responsibility |
|------|----------------|
| `protocol/specs/2026-07-08-enumeration-protocol.md` | Wire contract for levels + locators |
| `implementations/python/.../lift_rpc.py` | `_handle_enumerate` levels |
| `implementations/python/.../factory/literal_call_report.py` | `call:` / `method:` emission (batch truth) |
| `implementations/rust/sugar-compiler/src/tree.rs` | Typed tree + `enumerate_rpc` |
| `implementations/rust/sugar-compiler/src/kit.rs` | `Kit::rendezvous`, `lift`, `testimony`, conn |
| `implementations/rust/sugar-compiler/src/feed_from_tree.rs` (**new**) | Tree node → `ProofGraph` + fold |
| `implementations/rust/sugar-proof-envelope/src/proof_graph.rs` | `feed`, `push_claim_contract`, members |
| `implementations/rust/sugar-verifier/src/utterance.rs` | Speaker-stamped intake (attribution pattern) |
| `implementations/rust/sugar-compiler/tests/enumerate_conformance.rs` | fold==blob / scan-seek gates |
| `implementations/rust/sugar-compiler/tests/feed_from_tree.rs` (**new**) | graph fold gates |
| `implementations/rust/sugar-cli/tests/cross_proof_imported_implications.rs` | pandas `call:sum` / universe showcase |

---

## Campaign A — Enumerate completeness (old drive = reference)

### Task 0: Instrument the gap (red first)

**Files:**
- Create: `implementations/rust/sugar-compiler/tests/enumerate_completeness.rs`
- Modify: `implementations/rust/sugar-compiler/tests/fixtures/` (minimal pandas-shaped or existing enumerate fixture + a `sum`-like method call + builtin `len` if needed)
- Test: same file

**Interfaces:**
- Consumes: existing `Kit::rendezvous`, `CallSite::universe`, `enumerate` levels
- Produces: red tests that define `R` for Campaign A

- [ ] **Step 1: Write the failing completeness instrument**

The instrument must fail on current main for each of:

1. `CallSite::universe()` is `NotModeled` (or returns empty) when batch `lift` IR for the same file contains a matching `function-contract` / builtin-universe row.
2. Fold of enumerate levels does **not** include universe member names that appear in batch `payload.ir`.
3. At least one callsite identity is asserted explicitly: if batch emits `method:sum` (or `call:len`), the tree's call-site audit / memento / payload carries that same bridge symbol (not an ambiguous bare `sum`).

Skeleton:

```rust
#[test]
fn enumerate_universe_level_matches_batch_ir_universes() {
    // stage fixture; rendezvous python kit
    // batch = facts_and_universes_from_whole_project_lift(...)
    // tree  = universes_from_tree_walk(...)
    // assert tree universe names == batch universe names (sorted)
    // TODAY: tree empty / NotModeled → FAIL with R = count of missing universes
}
```

- [ ] **Step 2: Run and record R**

```bash
cd implementations/rust && cargo test -p sugar-compiler enumerate_universe_level -- --nocapture
```

Expected: FAIL; capture missing universe count and missing identity symbols as `R`.

- [ ] **Step 3: Commit the red instrument only**

```bash
git add implementations/rust/sugar-compiler/tests/enumerate_completeness.rs
git commit -m "Instrument enumerate completeness vs batch IR (red)"
```

---

### Task 1: Serve `level=universe` from the Python kit

**Files:**
- Modify: `lift_rpc.py` (`_handle_enumerate`)
- Modify: `protocol/specs/2026-07-08-enumeration-protocol.md` Section 3–4
- Modify: `tree.rs` (`CallSite::universe`, decode)
- Test: `enumerate_completeness.rs`, `enumerate_conformance.rs`, python `tests/test_enumerate_rpc.py` if present

**Interfaces:**
- Consumes: `_lift_file_for_enumeration` → `payload.ir` items
- Produces: nodes at `level="universe"` with memento + audit + optional FOL payload

**Semantics (old drive):**

- Universe rows in batch IR are primarily `kind="function-contract"` with formals / body law, plus operator-level builtin universes (`len::builtin-universe`, etc.).
- `CallSite::universe()` seeks the universe **linked to that callsite** (by `bridgeSourceSymbol` / callee identity), not every universe in the file.
- File-level scan (`at` = file memento, `seek=false`) may list all universes in the file for completeness auditing.

- [ ] **Step 1: Extend `_handle_enumerate` for `level == "universe"`**

```python
if level == "universe":
    # Require at.file (same security resolve as other sub-file levels).
    # From ir_items:
    #   - kind == "function-contract" rows that are body/operator universes
    #   - (optional filter) bridgeSourceSymbol matches call-site identity when at is a call-site memento
    # Emit nodes: {memento, audit: item, payload: inv|post formula if present}
    # Missing link when seeking a callsite with no universe → gap node with reason
    #   "no universe sugar for callee <name>"  (#3896 shape)
```

Reuse `_item_memento`, `_memento_matches`, path-escape checks. Do **not** invent a second lift: only slice `ir_items`.

- [ ] **Step 2: Implement `CallSite::universe` on the Rust tree**

Replace `NotModeled` with a real `enumerate_rpc(..., Level::Universe, at=callsite memento, seek=true)`.

```rust
pub fn universe(&self) -> Result<Option<Universe>, KitError> {
    let (nodes, gaps) = enumerate_rpc(
        &self.conn,
        Level::Universe,
        Some(self.memento.to_json()),
        true,
    )?;
    // 0 nodes + gap "no universe sugar..." → Ok(None) or Err typed gap — pick ONE
    // and stick to it; prefer Ok(None) + gaps() accessor so solve can treat absence
    // as link-class later without panicking the walk.
    ...
}
```

- [ ] **Step 3: Green the Task 0 instrument for universe count**

```bash
cargo test -p sugar-compiler enumerate_universe_level -- --nocapture
```

- [ ] **Step 4: Update protocol spec Section 3 row for `universe`** from "not modeled" to the landed backing (`function-contract` + builtin universe rows; seek by callsite memento).

- [ ] **Step 5: Commit**

```bash
git commit -m "Part of #3867: sugar.enumerate level=universe from factory IR"
```

---

### Task 2: Make callsite identity first-class (`call:` / `method:`)

**Files:**
- Modify: `lift_rpc.py` (call_sites / assertions node audit)
- Modify: `tree.rs` (`CallSite` fields or audit decode)
- Modify: protocol spec locator section
- Test: completeness instrument arm 3; optionally re-check pandas showcase once mint path consumes same identity

**Interfaces:**
- Produces: every call_sites node carries `bridgeSourceSymbol` (or dedicated field) equal to batch IR for that contract

- [ ] **Step 1: Red test** — tree call_site audit must equal batch item `bridgeSourceSymbol` for the fixture's method call and free call.

- [ ] **Step 2: Python** — when building call_sites nodes, put `bridgeSourceSymbol` (and `name`) on `audit` from the IR item (already on contracts). Ensure method calls keep `method:sum` and free calls keep `call:len` — **do not normalize away the prefix**.

- [ ] **Step 3: Rust** — decode into a typed field on `CallSite`:

```rust
pub struct CallSite {
    conn: KitConn,
    memento: SourceMemento,
    audit: Option<AuditRow>,
    /// e.g. "call:len" | "method:sum" — join key for universe/bridge
    bridge_source_symbol: Option<String>,
}
```

- [ ] **Step 4: Green identity arm of completeness instrument; commit**

```bash
git commit -m "Part of #3867: first-class call:/method: identity on enumerate call_sites"
```

---

### Task 3: Stop lying that call_site ≡ assertion (only if batch distinguishes)

**Files:** `lift_rpc.py`, `tree.rs`, protocol Section 4

- [ ] **Step 1: Measure** — on a fixture where batch IR has multiple claims per locus (or distinct assertion vs site records). If none exist in shipping IR, document that 1:1 is **factory truth**, not a protocol collapse, and close this task with a written receipt in the protocol spec (no code). Do not invent dual records without factory support.

- [ ] **Step 2: If dual records exist** — split levels: call_sites lists loci; assertions lists claim rows under a site memento. Update fold==blob to compare both sets.

- [ ] **Step 3: Commit** with either code or an explicit "1:1 is factory truth" protocol amendment.

---

### Task 4: Completeness gate upgrade (old drive as floor)

**Files:**
- Modify: `enumerate_conformance.rs` / `enumerate_completeness.rs`
- Reference: green-era pandas/cross_proof expectations (#3865)

- [ ] **Step 1: Expand fold==blob** beyond inv/post contracts:

```text
fold_set = {facts, universes, bridge_source_symbols}
blob_set = same extracted from Kit::lift IR
assert fold_set == blob_set
```

- [ ] **Step 2: Add discrimination** — fixture with a callsite that has **no** universe sugar → gap reason names callee (#3896); fixture with coverage → no gap.

- [ ] **Step 3: Run**

```bash
cargo test -p sugar-compiler enumerate_ -- --nocapture
# if fleet present:
# cargo test -p sugar-cli imported_pandas_sum -- --nocapture
```

- [ ] **Step 4: Commit**

```bash
git commit -m "Part of #3867: enumerate fold matches batch facts+universes+identities"
```

**Campaign A exit:** `R_universe = 0`, `R_identity = 0`, fold==blob includes universes. Production mint path still may use batch lift; enumerate is no longer a weaker sibling.

---

## Campaign B — Tree → ProofGraph via `feed`

### Task 5: Instrument "no feed path" (red)

**Files:**
- Create: `implementations/rust/sugar-compiler/tests/feed_from_tree.rs`
- Create: `implementations/rust/sugar-compiler/src/feed_from_tree.rs` (stub module)

**Interfaces:**
- Produces: red test `walk_and_feed_matches_minted_member_cids` (or fact FOL set)

- [ ] **Step 1: Write failing test** that stages the enumerate fixture, walks facts (and after A, universes), calls `feed_from_tree::fold_project(kit, root, speaker)`, and compares member CIDs / claim formulas to a graph built from today's mint/load path on the same fixture.

Expected: compile fail or empty graph until implemented.

- [ ] **Step 2: Commit red instrument**

```bash
git commit -m "Instrument tree-fold feed parity (red)"
```

---

### Task 6: `Fact` / universe audit → `ProofGraph` fragment

**Files:**
- Create: `sugar-compiler/src/feed_from_tree.rs`
- Modify: `sugar-compiler/src/lib.rs` (mod + re-export)
- Reuse: `ProofGraph::push_claim_contract`, `ClaimContractMemento`, patterns from `solve_two_reds.rs` / mint's IR→member construction

**Interfaces:**

```rust
/// Build a single-member (or few-member) graph from one enumerated claim node.
pub fn graph_from_fact(fact: &tree::Fact) -> Result<ProofGraph, FeedError>;

pub fn graph_from_universe(u: &tree::Universe) -> Result<ProofGraph, FeedError>;

/// Fold the full claim walk into one graph (no speaker yet).
pub fn fold_claim_tree(kit: &Kit, workspace_root: &Path) -> Result<ProofGraph, FeedError>;
```

- [ ] **Step 1: Implement `graph_from_fact`** by constructing the same contract member shape mint uses for `kind="contract"` rows (name, post/inv formula, source warrants from memento). Prefer calling shared helpers extracted from mint if they already exist in sugar-compiler/verifier; if mint helpers are CLI-private, **copy the minimal typed construction** into `feed_from_tree` rather than depending on sugar-cli.

- [ ] **Step 2: Implement `fold_claim_tree`**

```rust
pub fn fold_claim_tree(kit: &Kit, root: &Path) -> Result<ProofGraph, FeedError> {
    let mut g = ProofGraph::empty();
    for file in kit.source_files(root)? {
        for function in file.functions()? {
            for site in function.call_sites()? {
                if let Some(u) = site.universe()? {
                    g = g.feed(graph_from_universe(&u)?);
                }
                for assertion in site.assertions()? {
                    for fact in assertion.facts()? {
                        g = g.feed(graph_from_fact(&fact)?);
                    }
                }
            }
        }
    }
    Ok(g)
}
```

- [ ] **Step 3: Green feed_from_tree fact FOL parity (member content, not necessarily sealed bytes)**

- [ ] **Step 4: Commit**

```bash
git commit -m "Part of #3809: fold enumerate claim tree into ProofGraph via feed"
```

---

### Task 7: Feed as event — speaker attribution

**Files:**
- Modify: `proof_graph.rs` and/or pool intake path
- Prefer pattern already in `utterance.rs` (`member_speaker` first-writer-wins)

**Design choice (implementer must not invent a third attribution map):**

Attribution is a **pool intake** fact today (`MementoPool.member_speaker`). Options:

1. **Preferred near-term:** `fold_claim_tree` returns `ProofGraph`; a new `load_graph_with_speaker(graph, speaker) -> MementoPool` stamps every member CID at load (generalize self-load in `orchestrate.rs` which currently hardcodes consumer).
2. **Later:** `ProofGraph::feed(self, other, speaker)` if/when graph carries attribution (plan open seam).

- [ ] **Step 1: Red test** — consumer fact + vendor universe loaded with different speakers; `utterance::solve` / consistency labels show client vs vendor correctly (reuse consistency fixtures).

- [ ] **Step 2: Implement `pool_from_graph_with_speaker(graph, speaker)`** replacing the hardcoded `Speaker::consumer("solve-self-load")` for callers that pass a real speaker. Keep self-load path documented as fixture-only if still needed.

- [ ] **Step 3: Green; commit**

```bash
git commit -m "Part of #3809: stamp speaker at graph→pool intake"
```

---

### Task 8: One walk entry for project prove (thin face)

**Files:**
- Modify: optional experimental path in `cmd_prove` or a new `sugar-compiler` API used by a test harness first (prefer test harness before CLI cutover)

**Interfaces:**

```rust
pub fn prove_from_kit(
    kit: &Kit,
    workspace_root: &Path,
    speaker: Speaker, // consumer for local walk; vendor via kit.testimony()
    cfg: RunnerConfig pieces...
) -> Result<ProvenOutcome, SolveError>;
```

Algorithm:

1. `local = fold_claim_tree(kit, root)?`
2. `vendor = testimony proofs → read → feed` (existing `Kit::testimony`)
3. `graph = local.feed(vendor)` (CID monoid)
4. Either seal+write to temp and `solve_project`, **or** extend `solve_project` to accept a preloaded pool built with speakers

**Do not** delete batch mint yet. Gate: same fixture verdicts as `solve_project` on mint-produced `.proof`s for the enumerate fixture.

- [ ] **Step 1: Integration test only** (no CLI flag required)
- [ ] **Step 2: Commit**

```bash
git commit -m "Part of #3809: prove_from_kit folds tree+testimony into solve_project"
```

---

### Task 9: Retire the dual path (only after parity)

**Files:** CLI mint/prove faces, docs

- [ ] When `prove_from_kit` matches mint+prove on pandas + enumerate fixtures (byte-identical verdict rows where possible; labels only more correct):
  - Point one face through the fold path
  - Leave batch `Kit::lift` as implementation detail of enumerate file lift **or** as deprecated whole-blob API
  - Update #3822/#3809 with receipts

Out of scope for the first stack: exit-code redden (#3893), full utterance RPC for fact/universe/solve as CLI wire, sugar-walk purification (#3855).

---

## PR / merge sequence (Graphite-friendly)

| PR | Tasks | Standalone green? |
|----|-------|-------------------|
| PR1 | Task 0 | Yes — red instrument only (allowed: instrument PR) |
| PR2 | Tasks 1–2 | Yes — universe + identity |
| PR3 | Tasks 3–4 | Yes — completeness gate |
| PR4 | Tasks 5–6 | Yes — feed_from_tree facts/universes |
| PR5 | Task 7 | Yes — speaker intake |
| PR6 | Task 8 | Yes — prove_from_kit test harness |
| PR7 | Task 9 | Only when parity receipts exist |

Each PR: `cargo test -p sugar-compiler <filter>`; arch-guard if DAG edges change; python kit tests if `lift_rpc.py` changes.

## Validation matrix

| Check | Command |
|-------|---------|
| Completeness instruments | `cargo test -p sugar-compiler enumerate_ -- --nocapture` |
| Feed instruments | `cargo test -p sugar-compiler feed_from_tree -- --nocapture` |
| Two-reds / solve | `cargo test -p sugar-compiler solve_ -- --nocapture` |
| Python enumerate unit | `pytest implementations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py -q` (if present) |
| Demo surface (fleet) | `cargo test -p sugar-cli imported_pandas_sum -- --nocapture` |
| Arch | `cargo test -p sugar-arch-guard` |

## Explicit non-goals (this plan)

- Changing production exit codes for link errors (#3893)
- Merging `core::Term` and `IrTerm`
- Deleting `Kit::lift` batch RPC before fold parity
- Per-node wire laziness (file-granular re-lift stays acceptable)
- Full NDJSON utterance protocol as the only CLI face (later #3809 tranche)

## Risk register

| Risk | Mitigation |
|------|------------|
| Universe rows not 1:1 with callsites in IR | Seek by `bridgeSourceSymbol`; gap if none (#3896) |
| Mint helpers locked in sugar-cli | Extract shared typed builder into sugar-compiler or proof-envelope |
| feed without speaker scrambles labels | Task 7 before any face cutover |
| fold==blob green while old semantics red | Task 0/4 instruments must include universes + identities, not only facts |
| Spawn-per-enumerate cost | Out of scope; SEAM 7 residency; do not block correctness |

## Self-review

1. **Spec coverage:** #3867 gaps → Tasks 1–4; feed monoid design → Tasks 5–8; attribution seam → Task 7; one solve consumption → Task 8–9; #3896 gap shape → Task 1/4.
2. **Placeholders:** none intentional; Task 3 allows a documented no-op if factory is truly 1:1.
3. **Type consistency:** `Kit`, `CallSite`, `Universe`, `Fact`, `ProofGraph::feed`, `Speaker`, `ProvenOutcome` names match tree/orchestrate as of main post-#3891.
