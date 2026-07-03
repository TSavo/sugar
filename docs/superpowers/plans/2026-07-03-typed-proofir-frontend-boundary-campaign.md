# Typed ProofIR Frontend Boundary Campaign — IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first, and **verdict/byte-compatibility of compiled output is the acceptance bar on EVERY implementation slice** (`CompiledFormula` equality except differences admitted by the typed `FrontendProvenancePolicy` — see below; solver verdicts unchanged on the golden corpus). The instrument slice (S1) is PARALLEL-SAFE NOW — it measures without moving code. Read `docs/superpowers/specs/2026-07-03-typed-proofir-frontend-boundary-refactor.md` (T Savo, commit `1617f391d`, amended `93cf46af5` — THE SPEC; this plan executes it, it does not reinterpret it) and `AGENTS.md` (IDD manifesto + enforcement ladder + coordination-density invariant) before your first line. Every file:line below was verified against live main at `de39e9cd8`; re-verify against YOUR checkout — the exact lines drift as sibling campaigns merge, the shapes do not.

**Goal:** Move the existing IR compiler stack's frontend/backend boundary from transport JSON to typed ProofIR, so that serialization formats terminate at frontends and only typed obligations cross into backends. Completion test is the spec's, verbatim and strict:

> Replace the JSON frontend with a binary frontend and make **zero backend changes**.

## The decision of record (T Savo, 2026-07-03; spec §5 and §11, verbatim)

> **Serialization formats terminate at frontends. Typed obligations cross into backends.**

> **Types travel. Formats terminate. Backends lower typed obligations; they do not decode source transport.**

Not allowed at backend ingress after the refactor: `serde_json::Value`, `Json`, `RawValue`, `&str` as source obligation, `Vec<u8>` as source obligation. Allowed at frontend ingress: `decode(&str | &[u8]) -> Result<TypedProofIr, FrontendError>` and generated construction. Backend code may still emit target-language strings — the law governs what carries ProofIR *meaning* across the boundary, not what the backends produce.

**Spec amendment (T Savo, PR #3334, `93cf46af5`) — two typed policies, both load-bearing:**

1. **Typed frontend errors.** Decode failures cross machine boundaries as typed JSON-RPC error data, never string sludge: `FrontendErrorKind { MalformedTransport, UnknownInputKind, InvalidTypedIr, UnsupportedLegacyVariant }` carried in a `FrontendErrorPayload { kind, frontend, input_format, path, detail, retirement }`. The RPC-server-as-frontend is explicitly a named compatibility hatch under the seven-point interface rule (owner, input, output, addressing, failure type, replay inputs, retirement). A `Failed(String)`-shaped frontend error is the lift-plugin bug (#3316) reborn — REJECT-level.
2. **Typed provenance policy.** `sugar-ir-compiler` owns the allowed set of cross-frontend output differences via `FrontendProvenancePolicy { owner, allowed_fields: Vec<CompiledFormulaFieldPath>, reason, retirement }`. **Default policy is EMPTY: JSON frontend output == binary frontend output, byte-for-byte.** Any difference must be admitted by typed policy with owner/reason/retirement — not a comment, not test folklore. Instrument C fails on unadmitted differences.

This is NOT a new compiler (spec §2). The compiler spine exists: `sugar-ir-compiler` (trait, registry, JSON-RPC subprocess client/server, manifest loader), four bundled backends (SMT-LIB, Lean, Coq, Maude), `sugar-verifier/src/solvers/plan.rs` routing `CompiledFormula` to `solve_compiled`. The typed substrate exists: `sugar-ir-types` defines `IrTerm`/`IrFormula` (aliased `Term`/`Formula`), and **every backend already deserializes JSON into those types internally** (spec §4 — verified live: `compile_to_parts` in smt-lib and lean, `compile_inner` in coq, `compile_artifact` in maude all call `serde_json::from_value` at compile ingress). The JSON step is an ingress artifact, not the semantic substrate. The work is relocating decode across a boundary, not building anything.

## Why this campaign is the board's center of gravity

Every typed boundary landed this week — PostCondition into FunctionContract (CL S6), the route-raises spine (Phase 2), the conformance walker (#3318/#3319) — terminates at a compiler that eats `&Json` at the front door. By the discharge law (interface map §5), a perfectly typed formula that gets serialized into ambient JSON and re-parsed by an opaque compiler has discharged nothing. Conversely, once this boundary is typed:

- The conformance census's compiler-ingress row class retires by **unrepresentability**, not by drain (you cannot pass an undeclared `Value` through a door that does not take `Value`).
- The one-dumb-test's middle assertion ("THAT node was emitted") gains a typed fact at the pipeline's narrowest point, inherited by every enrolled witness for free.
- Ambient testimony cannot transit the middle of the system; it is squeezed to the edges where #3314/#3316 are already aimed.

Ownership after the refactor (spec §9) is conserved: frontends own transport decode and malformed-transport rejection; the compiler middle/backend owns type-directed normalization, target admissibility, lowering, opacity, and target metadata; solver adapters own running tools over `CompiledFormula`; the verifier owns plan choice and verdict interpretation. **Compiler opacity stays load-bearing** — this campaign types the door, never the interior. `CompiledFormula` remains richer than `script()`: `opacity_manifest` and `metadata` survive unchanged (Maude's `metadata.maude.moduleSource`/`queries`/`trs` side-table is the existence proof for why `metadata` is compiler product, spec §9).

## The offender census (S1 seed; verified live at `de39e9cd8`; NOT solved in S1)

| # | Offender | Where (verify locally) | Class | Retirement | Drain slice |
|---|---|---|---|---|---|
| 1 | `IrCompiler::compile(&self, ir: &Json, dialect)` trait method | `sugar-ir-compiler/src/lib.rs` (~98-107) | backend trait ingress is transport JSON | `compile_typed(&CompilerInput)` becomes the trait; old method demoted to adapter, then deleted | S2 (introduce) / S7 (delete) |
| 2 | `Registry::compile(ir: &serde_json::Value, ...)` | `sugar-ir-compiler/src/registry.rs` (~47-58) | registry preserves untyped ingress | registry dispatches `&CompilerInput` | S4 |
| 3 | `SmtLibCompiler::compile(&Json)` + `compile_to_parts`/`compile_asserted_to_parts`/`emit` calling `serde_json::from_value` at ingress | `sugar-ir-compiler-smt-lib/src/lib.rs` (~42-48, ~243-282) | backend decodes transport | receives `CompilerInput::{Formula,Term}`; decode moves to frontend adapter | S3a |
| 4 | `LeanCompiler::compile(&Json)` + `compile_to_parts` `from_value` | `sugar-ir-compiler-lean/src/lib.rs` (~35-41, ~89-114) | backend decodes transport | same as row 3 | S3a |
| 5 | `CoqCompiler::compile(&Json)` + `compile_inner` `from_value` | `sugar-ir-compiler-coq/src/lib.rs` (~56-71, ~81-99) | backend decodes transport | receives `CompilerInput::{Formula,Term}` | S3b |
| 6 | `MaudeCompiler::compile(&Json)` + `compile_artifact` raw-JSON `RawObligation` decode | `sugar-ir-compiler-maude/src/lib.rs` (~56-109, ~134-140, ~162-165) | backend owns raw JSON shape decoding | receives `CompilerInput::EquationalTheory(EquationalTheoryObligation)` — the variant is minted FOR this row | S3b |
| 7 | `LazyJsonRpcCompiler::compile(&Json)` / `JsonRpcCompiler::compile(&Json)` + `ir_json` request params | `sugar-ir-compiler/src/subprocess.rs` (~186-243) | RPC wrapper doubles as backend contract | remains JSON-RPC *transport glue* (frontend), re-classified; wire shape `sugar.ir.compile`/`ir_json` conserved (spec §7 Phase 4 route 1) | S5 |
| 8 | RPC server decodes `params.ir_json` then calls `compiler.compile(&ir, ...)` | `sugar-ir-compiler/src/server.rs` (~69-89) | server hands transport JSON to backend | server decodes `ir_json → CompilerInput` before invoking backend | S5 |
| 9 | `run_plan_with_compilers(..., formula: &Json)` | `sugar-verifier/src/solvers/plan.rs` (~69-81) | verifier plan carries transport JSON as the obligation | typed `formula: &CompilerInput` (or `&sugar_ir_types::Formula` if only formulas reach this path — decide at S4 with evidence) | S4 |
| 10 | `solver_input` Precompiled arm falls back to `formula.map(Json::to_string)` as solver text | `sugar-verifier/src/solvers/plan.rs` (~404-432) | **found during plan verification, not in the spec** — a second untyped egress: the obligation JSON is stringified directly as solver input for non-smt-lib solvers on the precompiled path | classify at S4: route through a compiler or refuse loudly; never silently stringify ProofIR as solver text | S4 |

**Declared allowlist (spec §8-B) — these are NOT offenders; they become DECLARED hatches in `conformance/typed_pipeline/interfaces.toml` with owner + retirement:**
- `CompiledFormula.metadata: Json` while it remains declared dialect metadata (`sugar-ir-compiler/src/lib.rs` ~42-47). Owner: this campaign. Retirement: typed per-dialect metadata enums if/when a second consumer appears; until then it is compiler side-table by design.
- `IrTerm::Const.value: serde_json::Value` (`sugar-ir-types/src/lib.rs` ~345-349) — a literal value *inside* typed IR, intentionally `Value`. Owner: sugar-ir-types. Retirement: typed literal union if the sorts campaign demands it; not this campaign's fight.

## Campaign law

1. **Instruments before drains.** S1 lands the auditors RED against the census before any production line moves.
2. **Verdict/byte-compat is the floor on every implementation slice.** `CompiledFormula` output equality (except differences admitted by the typed `FrontendProvenancePolicy` — default EMPTY, owner `sugar-ir-compiler`; spec `93cf46af5`) across the refactor, demonstrated per slice with a planted-drift control; solver verdicts on the golden corpus unchanged. A deliberate output change files a soundness issue first.
3. **Target-admissibility checks stay backend-local** (spec §7 Phase 2): SMT-LIB's empty-var validation, mixed-sort-conjunction detection, and unreduced `substitute`/`apply`/`divergence-between` refusal are semantic checks on typed input, NOT transport decoding. Moving them to the frontend is a REJECT-level review defect.
4. **One seam, one owner.** This campaign owns the compiler ingress seam. Conformance #3320 re-scopes to consume this campaign's ratchets (comment posted); vocab #3240's Rust membership mirror slots after S2 and consumes `CompilerInput` as its landing zone (comment posted).
5. **No new compiler, no new IR.** `CompilerInput` wraps `sugar_ir_types` types; it does not fork them. Any impulse to "improve" `IrFormula` while passing through is scope theft from the sorts/vocab campaigns — flag, don't do.

## Instruments

### Instrument A — no transport JSON at backend ingress (S1; rung: auditor)
Static scan (house pattern: a Rust test that reads the live source of the compiler crates) failing on any `impl IrCompiler for *` whose `compile`/ingress signature carries `&Json`/`&serde_json::Value`, seeded with census rows 1-9 as the declared baseline (non-regressing). Reports `R(transport-json-backend-ingress)`.
**Law-8 confession + retirement:** the auditor exists because the trait still HAS the JSON method; the typed trait itself (S2→S7) retires rows mechanically — when `compile(&Json)` is deleted from the trait (S7), an offender is a compile error and Instrument A's axis goes to *unrepresentable*, the auditor deleted.

### Instrument B — backend phase cannot call frontend decode (S1; rung: auditor)
Same test walks backend compile entrypoints (`compile_to_parts`, `compile_asserted_to_parts`, `emit`, `compile_inner`, `compile_artifact`) and reds on `serde_json::from_value` applied to the obligation payload, seeded with census rows 3-6. Allowlist: the two §8-B entries above, plus `decode_json` itself once S2 lands (it IS the frontend adapter — the one place `from_value` is legal). Reports `R(backend-decode-callsites)`.
**Retirement:** drains to zero via S3a/S3b; after S7 the backends have no `&Json` to decode and the axis is unrepresentable; auditor deleted.

### Instrument C — binary-frontend zero-backend-diff test (S6; rung: test, permanent)
The spec §7 Phase 5 five-step acceptance: decode JSON fixture → `CompilerInput`; decode equivalent binary fixture → `CompilerInput`; assert typed equality; compile both through the SAME backend (SMT-LIB + at least one non-SMT backend); assert `CompiledFormula` equality except fields admitted by the typed `FrontendProvenancePolicy` (spec `93cf46af5`; default policy EMPTY — JSON output == binary output byte-for-byte; Instrument C FAILS on any unadmitted difference). Fails if the binary frontend required backend changes or backend output depends on source serialization. **This instrument does not retire** — it is the standing proof of the completion test and the regression tripwire for any future frontend.

## Ratchet vector

| Axis | Baseline (S1 pins; verify live) | Target |
|---|---|---|
| `R(transport-json-backend-ingress)` | 9 (census rows 1-9) | 0, then unrepresentable (S7 trait deletion) |
| `R(backend-decode-callsites)` | rows 3-6 (count the live `from_value` sites at S1) | 0, then unrepresentable |
| `R(untyped-verifier-obligation-paths)` | 2 (census rows 9-10) | 0 |
| `R(frontend-provenance-unadmitted)` | 0 (default `FrontendProvenancePolicy` is EMPTY) | stays 0 — any cross-frontend output difference is admitted by typed policy (owner/reason/retirement) or Instrument C reds |
| `R(compiled-output-drift)` | 0 | 0 at every slice (floor, with planted control) |

## Slices

### Slice 0 — Plan PR
This document, committed to main. Issues filed per slice. #3320/#3240 reconciliation comments posted. Exit: merged.

### Slice 1 — Instruments A + B, RED/measuring — PARALLEL-SAFE NOW
Build the auditor test (suggested home: `sugar-ir-compiler/tests/frontend_boundary_conformance.rs`, or extend the house conformance walker — worker's choice, state the rung either way) that (a) reds on `&Json` in `IrCompiler` impl compile signatures, (b) reds on `from_value` at backend compile ingress, seeded with the census as declared-with-retirement baseline rows. Add the two §8-B allowlist entries to `conformance/typed_pipeline/interfaces.toml` as declared escape hatches with owner+retirement (coordinate: the walker's manifest is the house registry now; if rows are added, comment on #3319/#3323). Note the amendment's typed policy vocabulary (`FrontendErrorKind`/`FrontendErrorPayload`/`FrontendProvenancePolicy`, spec `93cf46af5`) as declared vocabulary in the instrument's baseline so S5/S6 reds are pre-named. NO production change.
- Red-first: the test written against an empty baseline reds with all census rows named; seeding the baseline turns it green; a PLANTED offender (a temp-file `impl IrCompiler` with `&Json`, and a planted `from_value` at a backend ingress) reds through the real detection path — receipts in the PR.
- Bad-twins: (a) planted offender detected; (b) a legal `from_value` in a frontend adapter position (fixture) NOT flagged (discrimination); (c) dropped baseline row reds.
- Exit: both R axes pinned with baseline values; planted receipts; zero production diff.

### Slice 2 — `CompilerInput` + `compile_typed` + `decode_json` adapter (spec Phase 1)
In `sugar-ir-compiler`: add `pub enum CompilerInput { Formula(sugar_ir_types::Formula), Term(sugar_ir_types::Term), EquationalTheory(EquationalTheoryObligation) }` (spec §6 — the Maude obligation type gets defined here or re-exported from a maude-owned location; decide with evidence about where `RawObligation`'s shape truly lives, flag if it must stay maude-local) plus a frontend module (`src/frontend.rs`) owning `CompilerInput::decode_json(serde_json::Value) -> Result<Self, FrontendError>` — `FrontendError` carries the amendment's typed shape (`FrontendErrorKind { MalformedTransport, UnknownInputKind, InvalidTypedIr, UnsupportedLegacyVariant }` + `FrontendErrorPayload { kind, frontend, input_format, path, detail, retirement }`, spec `93cf46af5`), never a bare string — (kind-dispatch: term kinds → `Term`, maude equational-theory shape → `EquationalTheory`, else `Formula` — mirror the existing `is_term_kind` gates so decode agrees byte-for-byte with what backends currently do). Add `compile_typed(&self, ir: &CompilerInput, dialect: &str)` to the trait with a default impl NOT provided — instead keep `compile(&Json)` as a *provided* compatibility adapter delegating `decode_json → compile_typed` per spec §7 Phase 1 (note: this inverts which method is required; every impl must provide `compile_typed`, which is exactly the one-flip enrollment pattern — the compile error enumerates the four backends).
- Red-first: a test calling `compile_typed` on the registry's SMT-LIB compiler before the method exists (compile-red).
- Bad-twins: (a) `decode_json` on a formula fixture == what `compile_to_parts` decoded internally (typed equality); (b) malformed transport refuses with `FrontendError`, never a backend error; (c) a term-kind fixture routes to `Term`, not `Formula`.
- Byte-compat: all four backends' outputs on the golden corpus identical before/after (they now decode via the adapter path); planted control.
- Exit: `CompilerInput` exists; trait has `compile_typed` required + `compile` adapter; `R(transport-json-backend-ingress)` unchanged (the adapter is declared); zero output drift.

### Slice 3a — Move decode out of SMT-LIB + Lean backends (spec Phase 2, batch 1)
`SmtLibCompiler`/`LeanCompiler` implement `compile_typed` natively on `CompilerInput::{Formula,Term}`; their `from_value` ingress calls delete; `compile_to_parts(&Json)` public helpers become thin `decode_json` + typed-core wrappers or move behind the frontend (keep public API compat where external callers exist — census them in the PR). Target-admissibility checks (empty-var, mixed-sort, wp-schema refusal) stay in the backend operating on typed input.
- Red-first: Instrument B rows for smt-lib/lean red until the moves land.
- Bad-twins: (a) admissibility refusals fire identically on typed input (same error strings — they are pinned by tests); (b) bare-term legacy path still compiles byte-identically; (c) planted `from_value` reintroduction reds.
- Exit: `R(backend-decode-callsites)` drains smt-lib+lean rows; byte-compat 0 drift; verdict-compat on golden corpus.

### Slice 3b — Move decode out of Coq + Maude backends (spec Phase 2, batch 2)
Same shape. Maude is the care point: `compile_artifact`'s `RawObligation` decode becomes `CompilerInput::EquationalTheory` construction at the frontend; the TRS/`moduleSource`/`queries` metadata emission stays backend-owned (spec §9 — that is compiler product, not transport).
- Bad-twins: (a) Maude metadata side-table byte-identical; (b) an equational-theory document mis-tagged as Formula refuses at decode, not inside Maude; (c) Coq term/formula split conserved.
- Exit: `R(backend-decode-callsites)` = 0; byte/verdict-compat receipts.

### Slice 4 — Registry + verifier plan typed (spec Phase 3)
`Registry::compile` takes `&CompilerInput`. `run_plan_with_compilers` takes typed obligation (census row 9): `&CompilerInput`, or `&sugar_ir_types::Formula` if evidence shows only formulas reach this path — decide with a callsite census in the PR, per spec §7 Phase 3. Resolve census row 10 (the `Json::to_string` fallback in `solver_input`'s Precompiled arm): route it through a compiler or make it a loud refusal; a silent stringification of ProofIR as solver text may not survive. Callers (runner, cmd_prove, wherever `formula: &Json` originates) decode ONCE at their ingress via `decode_json` — the frontend adapter isolates upstream JSON until the vocab campaign types those layers.
- Bad-twins: (a) a plan over a typed formula produces the identical verdict + invocation vector as before; (b) the row-10 path either compiles or refuses loudly (test both); (c) no-compiler-for-dialect error path unchanged.
- Exit: `R(untyped-verifier-obligation-paths)` = 0; `run_plan_with_compilers(formula: &Json)` gone; byte/verdict-compat.

### Slice 5 — JSON-RPC as transport frontend (spec Phase 4, route 1)
Wire shape conserved: method `sugar.ir.compile`, params `ir_json` — protocol compat is a floor (external plugin ecosystem). The RPC *server* decodes `params.ir_json → CompilerInput` before invoking the backend (census row 8); it is an explicitly NAMED compatibility hatch under the seven-point interface rule (spec `93cf46af5`), and decode failures cross the wire as typed JSON-RPC error data — `FrontendErrorPayload`, never string sludge. `JsonRpcCompiler`/`LazyJsonRpcCompiler` are re-classified as transport frontends: they serialize `CompilerInput → ir_json` on the client side and stay off the backend trait's typed path (they implement `compile_typed` by encoding; the JSON they speak is wire, not boundary). Depends on S2 only — parallel-safe with S3/S4.
- Bad-twins: (a) an existing external-plugin fixture round-trips byte-identically; (b) malformed `ir_json` refuses server-side with a TYPED `FrontendErrorPayload` (kind + frontend + input_format + retirement), backend never sees it; (c) the subprocess transport-failure retry path conserved; (d) a planted string-sludge error path reds the conformance walker.
- Exit: census rows 7-8 drain; wire protocol byte-identical; `R(transport-json-backend-ingress)` residue = the trait adapter only.

### Slice 6 — Binary frontend + Instrument C (spec Phase 5)
`BinaryProofIrFrontend::decode(&[u8]) -> Result<CompilerInput, FrontendError>` over a canonical binary representation (worker proposes the encoding with a one-paragraph rationale — postcard/CBOR/etc.; the CHOICE is not load-bearing, the zero-backend-diff proof is). Land Instrument C, the five-step acceptance test, over SMT-LIB + one non-SMT backend. **The acceptance criterion is the spec's completion test: no backend file changes in this slice's diff.**
- Red-first: Instrument C written first, red for want of the frontend.
- Bad-twins: (a) JSON-decoded and binary-decoded `CompilerInput` typed-equal on the fixture corpus; (b) a corrupted binary fixture refuses at decode (typed `FrontendErrorPayload`); (c) `git diff --stat` of the slice shows zero lines in `sugar-ir-compiler-{smt-lib,lean,coq,maude}` (assert it in the PR body — this IS the proof); (d) with the default-EMPTY `FrontendProvenancePolicy`, outputs byte-equal; a PLANTED unadmitted difference reds Instrument C; an admitted difference (policy row with owner/reason/retirement) passes — all three tested.
- Exit: Instrument C green and permanent; completion test demonstrated.

### Slice 7 — Close: delete the adapter, arm the gates, retire the auditors
Delete `compile(&Json)` from the trait (or pin as named residue with evidence if an external-plugin constraint genuinely forbids it — decide loudly). Migrate stragglers the compile error enumerates. Drain Instruments A/B to zero and DELETE them (their axes are now unrepresentable — the ladder's endgame); Instrument C stays as the permanent gate. Update `interfaces.toml`: compiler-ingress hatch rows retire; `CompiledFormula.metadata` row survives as the declared residue. Comment closure evidence on #3320 (its census rows drain here) and #3240 (landing zone confirmed for vocab S10).
- Bad-twins: (a) a planted `compile(&Json)` impl fails to compile; (b) Instrument C still green through both frontends post-deletion.
- Exit: campaign closure criteria (below) all true.

## Sequencing with sibling campaigns

- **Conformance campaign (#3318-#3323):** #3320 (its S6, "retire the compiler ingress &Json door") is SUPERSEDED in implementation by this campaign and re-scoped to the ratchet-consumer role: its census rows drain as S2-S5 land here; its close condition becomes "this campaign's S7 done + walker rows retired." Comment posted on #3320. New manifest rows from S1 coordinate with #3319/#3323.
- **ProofIR vocab campaign (#3240, Rust mirror S10):** `CompilerInput`/`compile_typed` is the concrete landing zone for the Rust membership layer; vocab S10 slots after this campaign's S2 and builds ON `CompilerInput`, not beside it. Comment posted on #3240.
- **irterm-boundary (#3196-#3198) / Phase 2 (#3295-#3298):** disjoint crates (sugar-walk / sugar-floor-algebra vs sugar-ir-compiler*/sugar-verifier solvers). No file overlap; slices here may run in parallel lanes with those campaigns. The only shared surface is golden-corpus verdict receipts — every lane runs them anyway.
- **Witness campaign:** the one-dumb-test's RPC path (`sugar lift → ir compiler → solver`) crosses this seam; S2-S5 must keep the witness triple suite green at every slice (it is in every validation matrix).

## Anti-goals

- **No new compiler, no new IR, no `sugar_ir_types` fork.** `CompilerInput` wraps existing types (spec §6). Variant additions beyond `{Formula, Term, EquationalTheory}` need a spec amendment from T, not a worker judgment call.
- **No typing the compiler interior.** Opacity is load-bearing (interface-map invariant 1). Backends' internal normalization/lowering stay opaque; `metadata` stays compiler side-table. Type the door, not the room.
- **No moving target-admissibility checks to the frontend.** Empty-var, mixed-sort, wp-schema refusals are semantic, backend-owned (spec §7 Phase 2).
- **No wire-protocol break.** `sugar.ir.compile`/`ir_json` shape conserved (route 1). A versioned `compileTyped` method is S-future, only with T's sign-off.
- **No silent output drift.** `CompiledFormula` equality except `FrontendProvenancePolicy`-admitted fields (default empty); solver verdicts conserved; planted-drift control in every implementation slice.
- **No string-sludge frontend errors.** Decode failures crossing any machine boundary carry the typed `FrontendErrorPayload`; a `Failed(String)`-shaped frontend error is #3316 reborn — REJECT-level.
- **No decode duplication.** `decode_json` is written ONCE (S2); backends and server call it; a second kind-dispatch ladder anywhere is a defect.

## Campaign closure

CLOSED when (spec §10, all eight):
1. The in-process backend trait accepts typed ProofIR input, not `serde_json::Value`.
2. JSON decoding lives in a frontend adapter or RPC transport adapter.
3. Binary decoding exists as another frontend adapter.
4. SMT-LIB, Lean, Maude, Coq (and future TPTP/Vampire) backends compile from the same typed input contract.
5. Replacing JSON frontend with binary frontend causes zero backend changes (Instrument C, permanent).
6. `CompiledFormula` remains richer than `script()`: opacity and metadata survive unchanged.
7. Solver planning still routes `CompiledFormula` to `solve_compiled` with conserved semantics.
8. Instruments forbid new backend ingress from accepting transport JSON — by then, as a compile error (Instruments A/B retired to unrepresentability; Instrument C standing).

Plus the house terms: every R axis at stable zero or unrepresentable, `R(compiled-output-drift)`=0 throughout, all conformance manifest rows for this seam retired or declared-with-owner.
