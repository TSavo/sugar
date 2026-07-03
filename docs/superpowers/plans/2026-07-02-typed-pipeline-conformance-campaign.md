# Typed-Pipeline Conformance Campaign — IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first, and **byte-compatibility of emitted proof/verifier/report output is the acceptance bar on EVERY implementation slice.** The instrument (S1) is PARALLEL-SAFE NOW — it measures without moving code. The drains are Rust-side and slot AFTER/alongside the irterm-boundary and Phase-2 campaigns per the byte-drift rules already established. Read `docs/superpowers/specs/2026-07-02-typed-pipeline-interface-map.md` (the six-spec set, §4 the seven-point interface rule, §5 the discharge law) and `AGENTS.md` (IDD manifesto + enforcement ladder) before your first line. Every claim below is grounded in file:line/spec-section; re-verify against live main.

**Goal:** Make the typed-pipeline discharge law enforceable. Turn the §4 seven-point interface rule from documentation into a REVIEW INSTRUMENT that CI inspects, so that a discharge is real only when its obligation, witness, boundary, and replay inputs are independently typed and addressable — and "ambient testimony" (self-referential discharge through an untyped or ambient boundary) becomes detectable, named, and non-regressing, then retired row by row until each escape hatch is a typed impossibility. **Types retire auditors when interfaces declare their proof obligations.**

## The decision of record (T Savo, 2026-07-02; map §5, verbatim)

**"A discharge is only real if the obligation, witness, boundary, and replay inputs are independently typed and addressable. Anything else is ambient testimony."**

This ties three layers together: (1) the §4 seven-point interface rule is not documentation — it is a REVIEW INSTRUMENT that turns interface design into something CI can inspect; (2) ir-compiler-solver invariant 1 (opacity is not free — it creates a new proof obligation); (3) the #3307/#3303 verifier incident (the ambient ground-callsite path letting a stated fact feed itself into its own obligation) is the same failure mode in another costume.

**The bug class:** *self-referential discharge through an untyped or ambient boundary.* Cross-layer, not solver-local — the verifier incident is the evidence.

**The campaign slogan:** *Types retire auditors when interfaces declare their proof obligations.*

**The declaration schema (§4, verbatim — this is what an interface must declare):** (1) Owner crate/module; (2) Input type; (3) Output type; (4) Addressing rule (CID/signature derivation); (5) Failure type (enum/diagnostic/refusal memento, not free-text across a substrate boundary); (6) Replay inputs (what a second verifier must pin to reconstruct the decision); (7) Legacy escape hatches (any `serde_json::Value`, raw string script, or ad-hoc parser that remains).

## The instrument's form (Law 8 — prefer the form closest to the compiler)

The §4 rule IS the declaration schema. Two candidate forms, per the enforcement ladder:

- **Registry + conformance test (buildable NOW, parallel-safe — the S1 form):** each seam declares its seven points into a checked-in `interfaces.toml` (or an in-code `InterfaceManifest` registry), including an explicit `escape_hatches` list where every entry carries an `owner` and a `retirement` path. A Rust conformance test (`sugar-cli/tests/typed_pipeline_conformance.rs`, rung: test/auditor) (a) fails if a new-or-modified interface type has no manifest entry, (b) fails on any escape-hatch SHAPE present in the interface (a `serde_json::Value` field, a `String`/free-text error variant crossing a machine boundary, a fallback-resolution path, an unscoped lookup key, a replay-irrecoverable input) that is NOT declared with an owner + retirement, (c) is seeded with the six census rows as declared-with-retirement baseline (non-regressing). This is the confession Law 8 names: Rust cannot yet generically type "this `Value` is a sanctioned escape hatch", so the auditor holds the line — but every row names the typed replacement that will retire it.
- **`#[sugar_interface(...)]` proc-macro (the ladder-climb endgame):** a derive/attribute on each boundary type that REQUIRES the seven-point declaration at the type and emits a COMPILE error when the type carries an undeclared `serde_json::Value`/free-text-error field. This is the top-rung form (compile-time, zero-latency). It is heavier to build; the coordinator decides whether S1 ships the registry form and a later slice promotes it to the macro, or S1 builds the macro directly. **Recommended:** S1 ships the registry+test (parallel-safe now), and each drain slice that lands a typed replacement moves that row from "declared escape hatch" toward "unrepresentable" — the macro is the capstone if the residue justifies it.

## The conformance baseline — the six census rows (S1 seed; NOT solved in S1)

These are not cleanup; they are the conformance baseline (map §5). Enumerable, named, non-regressing:

| # | Row (escape hatch) | Location | Owner | Retirement path | Drain slice |
|---|---|---|---|---|---|
| 1 | `legacy_response: Value` in `LiftPluginSession` | `sugar-cli/src/lift_plugin.rs:63-66` | lift-plugin seam | typed `claim` projections; `LiftResponseProjection` → deletion (spec §9) | S3 (#3316) |
| 2 | duplicate manifest shapes | `lift_plugin.rs:15-23` `LiftPluginManifest` vs `cmd_prove.rs` local `PluginManifest` | component-plan seam | unify on `PlannedLiftManifest` (map §3.3) | S5 (#3315) |
| 3 | `LiftPluginError::Failed(String)` across machine boundaries | `lift_plugin.rs:97-101` | lift-plugin seam | structured diagnostic/refusal memento (spec §6) | S3 (#3316) |
| 4 | `SolveResult.error`/`solver_stdout` unpinned strings | `sugar-verifier/src/solvers/mod.rs` | ir-compiler-solver seam | sidecar-CID-pinned evidence + structured exit metadata (spec §11) | S7 |
| 5 | `z3_path` fallback resolution | `RunnerConfig` (`solvers` spec §9) | ir-compiler-solver seam | config-driven solver plan only; classify fallback as compat (spec §11) | S7 |
| 6 | stage-vocabulary drift (`smt_emit` vs `smt_emitter`) | `runner.rs` `VERIFIER_STAGE_VOCABULARY` vs `protocol/specs/2026-05-13-proof-run-memento.md` | verifier seam | reconcile spec vocabulary deliberately (map §3.1) | S7 |

Plus the S10-shape row surfaced by §5 (the compiler ingress boundary — S6) and the self-referential-discharge axis (S2), and the data-access capstone (S8).

## Campaign law

1. **Instrument before drains.** S1 makes the drift enumerable, named, and non-regressing before any row is drained. It does NOT solve the six rows.
2. **Red-first every slice.** A new/modified interface without a manifest declaration is a red; an undeclared escape-hatch shape is a red; a discharge without independent testimony (S2) is a red.
3. **Every escape hatch is DECLARED with an owner and a retirement path — or it is a red.** No silent `serde_json::Value`, no free-text machine error, no fallback, no unscoped key, no replay-irrecoverable input crosses a boundary undeclared. A declared hatch is honest debt; an undeclared one is the bug class.
4. **The discharge law is sacred.** Obligation, witness, boundary, and replay inputs are independently typed and addressable, or the discharge is ambient testimony and refuses. Opacity is a NEW obligation (ir-compiler-solver invariant 1), never a free pass.
5. **Byte-compat is the acceptance bar every slice.** Baseline-vs-changed binary on the verify/emit/proof fixtures; `cmp` + SHA. Zero drift, or a soundness issue is filed and accepted first.
6. **Climb the ladder (Law 8).** The registry+test is a confession that types cannot yet say it; every drain slice moves a row toward unrepresentable. Prefer the fix that deletes a row's axis (a typed replacement) over the fix that keeps declaring it.

## Instruments

### Instrument A — the seven-point conformance walker (S1; the campaign's core)
Walks new-or-modified interface types; RED on undeclared `serde_json::Value`, raw string machine errors, fallback resolution, unscoped keys, or replay-irrecoverable inputs — unless each is declared as a legacy escape hatch WITH owner and retirement path. Reports `R(undeclared-escape-hatches)` + `R(interfaces-without-declaration)`. Seeded with the six census rows (declared, with retirement paths). **Law-8 annotation: justification (b) with a per-row retirement — the auditor confesses what Rust cannot yet type; each drain slice deletes a row by landing its typed replacement, and the whole auditor retires (or promotes to the `#[sugar_interface]` macro) when the residue is zero.**

### Instrument B — the discharge-law / ambient-testimony check (S2)
Makes "discharge without independent testimony" detectable: for each discharge, assert the obligation, witness, boundary, and replay inputs are independently typed and addressable (not the same ambient value feeding its own obligation — the #3307/#3303 shape). Reports `R(ambient-discharges)`. Cites ir-compiler-solver invariant 1 (opacity = new obligation) + §5 as contract. **Law-8: justification (b), coordinates with the #3307 Rust-side fix — that fix's issue, when filed, joins this frontier as the first `R(ambient-discharges)` drain.**

### Instrument C — byte-compat harness (every implementation slice)
Baseline-vs-changed binary on the proof/verify/report fixtures; `cmp` + SHA. `R(byte-drift)` starts 0, stays 0. **Law-8: justification (b), permanent — observable-output equality is the soundness floor.**

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(interfaces-without-declaration)` | S1 pins (every current pipeline seam). | 0 (every seam declares its seven points); armed as a gate. |
| `R(undeclared-escape-hatches)` | S1 pins the 6 census rows as DECLARED (baseline non-regressing); any UNDECLARED hatch is red. | undeclared = 0; declared rows drain to 0 as typed replacements land. |
| `R(ambient-discharges)` | S2 pins (the #3307/#3303 shape). | 0 — every discharge has independent typed testimony. |
| `R(byte-drift)` | 0. | 0 unless a soundness issue is filed and accepted. |
| `R(escape-hatch-rows-open)` | 6 (the census) + compiler-ingress + solver-telemetry. | 0 — each row retired to a typed replacement (or the macro). |

## Slices

### Slice 0 — Plan PR
Land this document. Comment #3314/#3315/#3316 (absorbed as drain slices), #3240 (the S10-shape precision), and #3307/#3303 (the ambient-testimony coordination).
Exit: merged as "Part 1 of the typed-pipeline conformance campaign (plan)".

### Slice 1 — THE INSTRUMENT (conformance walker + declaration schema + six-row baseline), RED/measuring — PARALLEL-SAFE NOW
Build Instrument A: the `interfaces.toml`/`InterfaceManifest` declaration schema (the §4 seven points, with `escape_hatches[{owner, retirement}]`) and the conformance test. Seed the six census rows as declared-with-retirement (the non-regressing baseline). Pin `R(interfaces-without-declaration)` and `R(undeclared-escape-hatches)`. NO production interface change — this only measures.
- Red-first: plant an undeclared `serde_json::Value` field on a pipeline interface → the walker reds naming it + demanding a declaration or retirement; a new interface with no manifest entry → red.
- Bad-twins: (a) a declared escape hatch (one of the six) with owner+retirement passes; (b) an undeclared hatch reds; (c) a modified interface losing its declaration reds.
- Decide the mechanical form at dispatch (registry+test recommended; macro is the ladder-climb).
Exit: the walker measures; the six rows are the pinned baseline; every current seam either declares or is a named red; parallel-safe and merged independent of the Rust byte-drift campaigns.

### Slice 2 — The discharge-law / ambient-testimony axis (Instrument B)
Build Instrument B: detect self-referential discharge through an untyped/ambient boundary (obligation, witness, boundary, replay inputs must be independently typed+addressable). Pin `R(ambient-discharges)` seeded from the #3307/#3303 shape. Coordinate with the #3307 Rust-side fix (its issue joins this frontier). Cite ir-compiler-solver invariant 1 + §5.
- Red-first: reconstruct the ambient ground-callsite path (a stated fact feeding its own obligation) → Instrument B reds; the typed-testimony fix greens it.
- Bad-twins: (a) a discharge with independent obligation+witness+boundary+replay → not flagged; (b) the ambient self-referential path → red; (c) an opaque compiler position with NO separate admissible discharge (invariant 1) → red (opacity is a new obligation).
Exit: `R(ambient-discharges)` pinned; the bug class is detectable; the #3307 fix is the first drain.

### Slice 3 — Drain: lift-plugin `legacy_response` + `Failed(String)` (absorbs #3316; census rows 1 & 3)
Migrate `legacy_response` consumers to typed `claim` projections; shrink `LiftResponseProjection` toward deletion; make `LiftPluginError::Failed(String)` a structured diagnostic/refusal memento where it crosses a replay artifact. Drains census rows 1 & 3. (Issue #3316 becomes this drain slice.)
Exit: rows 1 & 3 retired or declared-shrinking; witness assertion-2 reads a typed claim.

### Slice 4 — Drain: report/witness typed `WitnessSource`/`WitnessBundle` (absorbs #3314)
Type source selection / claim kind / input CIDs / toolchain scope before minting (`WitnessSource` enum + `WitnessBundle`, spec §11); evidence bytes stay CID-addressed sidecar. Preserve the invariants (evidence external+pinned; claim/evidence independently addressed; signatures cover witness CID; `actualOutputCids` requires `planCid`; fail-closed). (Issue #3314 becomes this drain slice.)
Exit: the report/witness minting seam declares typed source/claim/scope; the stringly `WitnessEntry.kind` is a closed enum.

### Slice 5 — Drain: component-plan manifest unification + `PlanArtifact` replay memento (absorbs #3315; census row 2)
Unify the duplicate manifest projections on `PlannedLiftManifest`; mint a `PlanArtifact` replay memento so a proof run pins the exact selected components rather than recomputing discovery (feeds report-witness replay pins). Drains census row 2. (Issue #3315 becomes this drain slice.)
Exit: row 2 retired; component selection is replay-pinnable; one typed manifest surface.

### Slice 6 — Drain: the compiler ingress boundary (the S10 shape)
`IrCompiler::compile(&self, ir: &Json, …)` is the naked-formula door (map §5). Route typed ProofIR members → the compiler ingress boundary (currently `Json` — the real boundary violation to retire or wrap) → `CompiledFormula`; `metadata: Json` survives ONLY as an explicitly classified/declared escape hatch. Coordinate with ProofIR-vocab Slice 10 (#3240) — this is where the Construction Law's Rust membership layer meets the compiler seam.
Exit: the compiler ingress is a typed member boundary (or a declared+owned wrap); `metadata: Json` is a declared hatch; #3240 cross-referenced.

### Slice 7 — Drain: solver telemetry + fallback + stage-vocab (census rows 4, 5, 6)
`SolveResult.error`/`solver_stdout` → sidecar-CID-pinned evidence + structured exit metadata; classify/retire the `z3_path` fallback as compat-only (config-driven plan is the interface); reconcile the `smt_emit`/`smt_emitter` stage-vocabulary drift deliberately. Drains census rows 4, 5, 6.
Exit: rows 4-6 retired or declared-compat; solver telemetry is typed/pinned.

### Slice 8 — Capstone: typed scoped key at the data-access layer
Replace the unscoped-lookup auditor with a typed scoped key: `BundleScopedCallsiteKey` / `VerifiedContract` (proof-envelope-pool spec §9) so an unscoped or raw-JSON member lookup is impossible by construction. This retires the auditor (Law-8 endgame: the illegal access path becomes unrepresentable).
Exit: the data-access layer cannot construct an illegal proof lookup; the unscoped-lookup auditor is deleted.

### Slice 9 — Close: arm the conformance gate; realize the slogan
Arm Instrument A as a GATE (`R(interfaces-without-declaration)=0`, `R(undeclared-escape-hatches)=0` for undeclared), Instrument B as a GATE (`R(ambient-discharges)=0`), and drive `R(escape-hatch-rows-open)` to zero (or promote the residue to the `#[sugar_interface]` macro). Every interface declares its seven points; every discharge has independent typed testimony.
Exit: the discharge law is enforced; auditors retired where types now say it; the slogan realized.

## Sequencing with sibling campaigns

- **irterm-boundary (#3191-#3198) + Phase 2 (#3292-#3298).** The drain slices (S3-S8) are Rust-side and slot AFTER/alongside these per the byte-drift rules already established (running an emission/interface byte change while a boundary campaign holds `R(byte-drift)=0` makes drift ambiguous). **S1 and S2 (the instruments) are PARALLEL-SAFE NOW** — they measure without moving code.
- **ProofIR-vocab Construction Law (#3232-#3240/#3300).** Slice 6 (compiler ingress) is the same seam as vocab Slice 10 (#3240, Rust membership); coordinate so the compiler `&Json` door is retired once, not twice. The vocab campaign types the CONSTRUCTION side; this campaign types the compiler INGRESS boundary they meet at.
- **The #3307/#3303 verifier fix.** Its Rust-side investigation/fix issue, when filed, joins this campaign's frontier as the first `R(ambient-discharges)` drain (S2). Cite invariant 1 + §5 as the contract.
- **The three prior gap issues (#3314/#3315/#3316)** are ABSORBED as drain slices S4/S5/S3 — restructured/chained under this campaign's instrument, audit trails preserved.

## Anti-goals

- **No undeclared escape hatch.** A `serde_json::Value`/free-text-error/fallback/unscoped-key/replay-irrecoverable input crosses a boundary DECLARED (owner + retirement) or it is a red. Silence is the bug class.
- **No ambient testimony.** A discharge whose obligation/witness/boundary/replay are not independently typed+addressable refuses — never self-referential discharge through an untyped boundary.
- **No opacity as a free pass.** An opaque compiler position without a separate admissible discharge is an open obligation (invariant 1), not a completed one.
- **No solving the six rows in S1.** S1 makes them enumerable and non-regressing; the drains solve them.
- **No Rust byte change during a holding boundary campaign.** Drains wait for the byte-drift window; the instruments do not (they measure).
- **No new campaign for the deferred cosmetic drifts.** The typed-already/cosmetic items (proof-envelope granularity, structured diagnostics) are declared-or-deferred rows, not campaigns.

## Campaign closure

1. Every pipeline interface declares its §4 seven points; `R(interfaces-without-declaration)=0`, armed as a gate.
2. No undeclared escape hatch crosses a boundary; the six census rows are retired to typed replacements (or the `#[sugar_interface]` macro holds the residue); `R(undeclared-escape-hatches)=0`, declared rows drained.
3. `R(ambient-discharges)=0`: every discharge has independent typed testimony; the #3307/#3303 bug class is unrepresentable; opacity is a tracked obligation.
4. The compiler ingress `&Json` door is retired or declared-wrapped; `metadata: Json` is a declared hatch (Slice 6 = vocab #3240 seam).
5. The data-access layer cannot construct an illegal proof lookup (`BundleScopedCallsiteKey`/`VerifiedContract`); the unscoped-lookup auditor is deleted.
6. Byte-compat holds across every slice; the slogan is realized: types retired the auditors because interfaces declared their proof obligations.
