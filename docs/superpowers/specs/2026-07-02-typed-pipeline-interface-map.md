# Typed Pipeline Interface Map

**Status:** grounded design draft against current `main` (`01264a8a9`).  
**Date:** 2026-07-02  
**Scope:** the typed seams from component discovery through lift, proof loading, IR compilation, solver execution, report rendering, and witness minting.

## 0. Why this exists

The current Sugar codebase already has typed Rust seams for most of the pipeline, but the interface story is spread across CLI modules, verifier modules, proof-envelope storage, component planning, solver configuration, and report-witness minting. This document is the map. The sibling documents in this set define each seam in interface-sized detail:

- `2026-07-02-component-plan-interface.md`
- `2026-07-02-lift-plugin-interface.md`
- `2026-07-02-proof-envelope-pool-interface.md`
- `2026-07-02-ir-compiler-solver-interface.md`
- `2026-07-02-report-witness-interface.md`

The design rule is: **typed boundaries are the substrate; JSON is a transport format, not the owner of meaning.** When a current codepath still carries JSON as an escape hatch, this document calls that out as a migration seam rather than pretending it is already typed.

## 1. End-to-end typed spine

```text
Workspace bytes
  -> ComponentPlan
  -> PluginEntry / PlannedLiftManifest / PlannedIrCompiler
  -> LiftPluginOptions + LiftPluginManifest
  -> LiftPluginSession { DomainClaim, legacy_response }
  -> ProofGraph / ProofEnvelope
  -> MementoPool { StoredMember indexes }
  -> CallSite / obligations
  -> CompiledFormula
  -> SolverInvocation / SolveResult
  -> Report
  -> ReportWitnessProof / WitnessMemento
```

Current source anchors:

| Segment | Current owner | Evidence |
|---|---|---|
| Component census and planning | `sugar-cli/src/component_plan.rs` | `PlanIntent`, `WorkspaceCensus`, `ComponentPlan`, `PlannedLiftManifest`, `PlannedIrCompiler` at lines 39-126; `plan_workspace_with_options` at lines 185-269. |
| Project/user config | `sugar-cli/src/project_config.rs` | `PluginEntry`, `WitnessEntry`, `ProjectConfig` at lines 16-166. |
| Lift dispatch | `sugar-cli/src/lift_plugin.rs`, `cmd_lift.rs` | `LiftPluginManifest`, `LiftPluginSession`, `LiftPluginOptions` at lines 22-81; `dispatch_lift_path` uses `libsugar::core::execute_path` at lines 173-263. |
| Prove orchestration | `sugar-cli/src/cmd_prove.rs` | `build_prove_report_with_options` reads config, plans components, configures witness discharge, builds `RunnerConfig`, and calls `Runner::new_with_compilers(...).run_with_proof_run()` at lines 259-321. |
| Verifier run | `sugar-verifier/src/runner.rs` | `RunnerConfig`, `ProofRunArtifact`, and `VERIFIER_STAGE_VOCABULARY` at lines 44-105; `run_with_proof_run_inner` starts at line 208. |
| Typed proof pool | `sugar-verifier/src/types.rs` | `MementoPool` stores `StoredMember` plus typed CID indexes at lines 45-168; `verify_by_hash` at lines 175-192. |
| IR compiler | `sugar-ir-compiler/src/lib.rs` | `CompiledFormula`, `OpacityManifest`, `Capabilities`, `IrCompiler` at lines 21-107. |
| Solver execution | `sugar-verifier/src/solvers/mod.rs`, `plan.rs`, `config.rs` | `SolveResult` and `Solver` at `mod.rs` lines 53-88; `SolverInvocation` and `run_plan_with_compilers` at `plan.rs` lines 23-81; config shape at `config.rs` lines 43-98. |
| Report witness | `sugar-cli/src/report_witness.rs` | `ReportWitnessProof`, `JsonWitnessOptions`, `mint_report_witness`, `mint_json_witness_with_options` at lines 21-220. |

## 2. Canonical boundary model

### 2.1 Planning boundary

The component planner is the generic workspace rendezvous boundary. It owns discovery and generic composition, but components own language/tool semantics over RPC. Current code already encodes this with:

```rust
pub enum PlanIntent { Lift, Prove, Verify }
pub struct ComponentPlan {
    pub plugins: Vec<PluginEntry>,
    pub lift_manifests: Vec<PlannedLiftManifest>,
    pub ir_compilers: Vec<PlannedIrCompiler>,
    pub diagnostics: Vec<ComponentDiagnostic>,
    pub census: WorkspaceCensus,
}
```

Design consequence: no downstream command should rediscover language ownership by scanning file extensions after planning. It should consume the plan's typed outputs or fail closed on `ComponentDiagnostic::Error`.

### 2.2 Lift boundary

The lift boundary has two outputs today:

```rust
pub struct LiftPluginSession {
    pub claim: DomainClaim,
    legacy_response: Value,
}
```

`DomainClaim` is the typed substrate output. `legacy_response` is still a compatibility escape hatch for report/render/mint code that has not been fully moved onto typed claim views. The design target is not to bless `legacy_response`; it is to make each consumer name the typed claim projection it needs.

### 2.3 Proof boundary

The proof boundary is content addressed. Current verifier code re-exports proof-envelope typed members and stores normalized members in `MementoPool`, not raw envelope JSON. That is the boundary to preserve:

```rust
pub struct MementoPool {
    pub mementos: BTreeMap<MementoCid, StoredMember>,
    pub atoms: BTreeMap<AtomCid, Vec<u8>>,
    pub body: BTreeMap<ContractBodyCid, Vec<u8>>,
    /* typed indexes */
}
```

Design consequence: callsites should ask pool methods and typed indexes for semantic facts. They should not rummage through raw JSON unless they are at a decoder/compatibility edge.

### 2.4 Compiler boundary

IR compiler inputs are canonical IR JSON values; compiler outputs are typed `CompiledFormula` values:

```rust
pub struct CompiledFormula {
    pub preamble: String,
    pub body: String,
    pub free_vars: Vec<FreeVar>,
    pub opacity_manifest: OpacityManifest,
    pub metadata: Json,
}
```

The string script is an artifact. The compiler identity, opacity manifest, free variable list, and metadata are part of the typed proof surface. A solver that needs metadata must read `CompiledFormula.metadata`, not recompile or parse comments from the emitted source.

### 2.5 Solver boundary

The solver interface is a typed trait with explicit identity and results:

```rust
pub trait Solver: Send + Sync {
    fn name(&self) -> &str;
    fn version(&self) -> &str;
    fn ir_compiler(&self) -> &str;
    fn identity(&self) -> SolverIdentity;
    fn solve(&self, smt: &str) -> SolveResult;
    fn solve_compiled(&self, compiled: &CompiledFormula) -> SolveResult;
}
```

The authoritative/companion split is represented by `SolverInvocation.authoritative`. Portfolio, chain, and dispatch behavior belong in `solvers::plan`, not in report formatting.

### 2.6 Report and witness boundary

`Report` is the terminal human/API summary. Witness minting is the replayable boundary. `mint_report_witness` turns `report_json` plus replay pins into:

- external evidence JSON pinned by CID,
- a signed witness pointer memento inside a `.proof`,
- `ReportWitnessProof` metadata carrying file paths and CIDs.

Design consequence: if a downstream user needs replay or admission, they should consume the witness proof and evidence CIDs. If they need UI, they can consume the report JSON.

## 3. Known current-code drifts to preserve explicitly

1. **Verifier stage vocabulary drift:** `runner.rs` currently declares `"smt_emit"` in `VERIFIER_STAGE_VOCABULARY`, while `protocol/specs/2026-05-13-proof-run-memento.md` names `smt_emitter`. New docs and code should use current code when describing execution, and a future cleanup should reconcile the spec vocabulary deliberately.
2. **Lift response is not fully typed yet:** `LiftPluginSession` carries `DomainClaim` plus `legacy_response`. The typed owner is `DomainClaim`; JSON response projections are migration debt.
3. **Component plan is typed, but manifest parsing has duplicate local shapes:** `cmd_prove.rs` has a local `PluginManifest` for witness discharge while `lift_plugin.rs` has `LiftPluginManifest`. This is a boundary worth consolidating once all manifest consumers agree on a single typed surface.
4. **ProofRunArtifact exists, but some receipt materialization is still aggregate:** `runner.rs` materializes stage receipts, but the fan-out stages currently share the same fanout input/output summary. The interface is typed; granularity can still improve.

## 4. Interface rule for future work

Every new Sugar interface should declare:

1. **Owner crate/module** — who constructs it.
2. **Input type** — exact Rust type or JSON schema if external.
3. **Output type** — exact Rust type or memento kind.
4. **Addressing rule** — how CIDs/signatures are derived.
5. **Failure type** — enum/diagnostic/refusal memento, not free-text if it crosses a substrate boundary.
6. **Replay inputs** — what has to be pinned for another verifier to reconstruct the same decision.
7. **Legacy escape hatches** — any `serde_json::Value`, raw string script, or ad-hoc parser that remains.
