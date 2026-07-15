# The implication-demand → per-edge linker seam (recon, 2026-07-15)

Reconnaissance map for reconciling implication DEMAND with the per-edge
LINKER/DISCHARGE path — the work that makes demand-driven enumeration
authoritative for linking rather than measured alongside it. Read-only survey
of origin/main; file:line citations current as of this date.

## Executive summary

1. Two per-edge implication paths exist and are NOT reconciled: a
   **demand/report path** (`demand_implication`) and the **actual discharge
   path** (`derive_link_bundle_inner` via `link`/`link_with_solvers`).
2. EMIT: `fold_implication_tree` walks every call site
   (`sugar-compiler/src/tree.rs:1503`), enumerates `Level::Implications`,
   deserializes the node `payload` into `sugar_linker::ImplicationDemand`
   (`tree.rs:1463`), runs `demand_implication` (`tree.rs:1470`).
3. An `ImplicationDemand` is keyed by **call edge + source contract +
   candidate contracts** (`sugar-linker/src/lib.rs:622-628`); the answer
   (`ImplicationDemandAnswer`, `lib.rs:641-651`) is attached to the lift
   report as `demanded_questions` evidence (`cmd_lift.rs:1427,562`).
4. CONSUME: the real linker (`link_with_solvers`, `lib.rs:847`) consumes
   `LinkerInputs{contracts, call_edges}` union, binds, mints
   `ObligationState`, and dispatches to the **solver registry** in
   `discharge_obligation` (`lib.rs:1562`), emitting the content-addressed
   `LinkBundle`.

## The four seams

- **SEAM 1 — solverless demand:** `demand_implication` discharges by calling
  `link(...)` with an **empty registry** (`lib.rs:802` → `link` builds
  `empty_registry` at `lib.rs:720`). Any structurally-distinct-but-equivalent
  implication reports `implication-undecidable` → `Unsatisfied`, though
  `link_with_solvers` would discharge it. Demand runs *alongside* the real
  discharge, not through it.
- **SEAM 2 — double mint / recompute:** `demand_implication` computes
  `obligation_evidence_term(post,pre)` itself (`lib.rs:799-800`), then `link`
  recomputes the same obligation + evidence term again (`lib.rs:947,957`).
  The ledger's minted obligation is never consumed by discharge — discharge
  recomputes it.
- **SEAM 3 — vocabulary collapse:** `ImplicationDemandStatus` has only
  `Discharged/Unsatisfied/Unjoined` (`lib.rs:630-636`), collapsing the richer
  `LinkerErrorKind` (`undecidable/timeout/refused/unprovable`,
  `lib.rs:485-501`). The status mapping at `lib.rs:806-820` loses
  solver-verdict granularity.
- **SEAM 4 — path divergence:** demand answers land in the **lift report**
  (`cmd_lift.rs:550-566`); the `LinkBundle` is produced separately by
  `sugar link`/linkerd from the union. Ledger entries are produced but never
  feed the bundle; the bundle never reads the ledger.

## What pins the seam today

- `sugar-linker/tests/implication_demand.rs` (2 tests):
  `one_resolvable_call_demand_mints_one_discharged_obligation` and
  `dangling_edge_demand_is_named_unjoined_debt_with_reason`.
- The standing restored-suite failures `test_construction_law*` and
  `predicate_call_prefix_claims` are **Python emit-side ProofIR-vocabulary
  tests** with zero references to implication/demand/linker/discharge — they
  pin the semantic-vocabulary campaign, NOT this seam.
- **No test currently pins demand-feeds-actual-discharge; that assertion is
  the missing gate.**

## Fix shape (input to a design decision, not a plan)

- **Owner boundary:** `demand_implication` (linker-owned, `lib.rs:749`) must
  be the single per-edge entry the discharge path also uses — it should take
  the **registry+plan** (like `link_with_solvers`) instead of hardcoding
  solverless `link()` at `lib.rs:802`, so the demanded answer *is* the
  discharged verdict.
- **Typed contract:** unify `ImplicationDemandStatus` with
  `LinkerErrorKind`'s verdict vocabulary (or embed the kind), so the report
  row and the `LinkBundle` linker-error carry the same typed verdict.
- **Single mint:** derive `ObligationState` once and thread it into both the
  report row and the bundle memento, retiring the duplicate
  `obligation_evidence_term` recompute (`lib.rs:799` vs `957`).
- **Seam to close:** make the `LinkBundle` derivation iterate
  `demand_implication` per edge (or vice-versa) so there is one per-edge
  worker, not two parallel ones.

## Key files

- `implementations/rust/sugar-linker/src/lib.rs`
- `implementations/rust/sugar-compiler/src/tree.rs:1430-1513`
- `implementations/rust/sugar-cli/src/cmd_lift.rs:534-566,1426-1428`
- `implementations/rust/sugar-linker/tests/implication_demand.rs`
