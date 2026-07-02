# Phase 2 — Effect Algebra + Control-Flow Routers — IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first, and **byte-compatibility of emitted contract/verifier output is the acceptance bar on EVERY implementation slice** — a slice that changes one emitted byte without a separately filed and accepted soundness issue has failed. The raise-routing ALGEBRA is already built and green (#3210, #3017 item 5); Phase 2 is the CONSUMER wiring: `?`/panic/early-return/Drop control flow routed as DATA through that spine, mirroring the Python `TrySugar` reference. Read `AGENTS.md` (IDD manifesto + enforcement ladder), `SHARED-LANGUAGE.md` (Contract, the implication edge), and the Python reference `sugar/try_sugar.py` before your first line. Every claim below is grounded in file:line; re-verify against live main.

**Goal:** Make Rust control-flow sugars ROUTERS over a typed effect family, mirroring the Python `TrySugar` reference: `Outcome::Incomplete` carries a typed effect; a router matches the effect against handlers (first match reduces, no match propagates the outcome UNCHANGED — propagation is "nobody consumed it", never simulated control flow); raises are DATA on the block frontier so a raise under an inner `if` can be caught by a wrapping handler. When this campaign closes, `?`, `panic!`, early-return, and Drop each enter the effect algebra deliberately and route through the ONE `RouteRaisesOperation` spine — not through structural guard synthesis (panic) or an opaque `op("try")` term (`?`). This unblocks irterm-boundary Slice 6 (#3196) → #3197 → #3198, which gates ProofIR-vocab Slice 9 (#3240): it is the last unplanned architecture chunk on the completion path.

## The decision of record (from #3025 + #3017 item 5, ratified — do not relitigate)

Phase 2 delivers (verbatim from #3025):
- **A typed effect family** (a `RaiseEffect`-equivalent for `panic`/`Result`-`Err`/early-return) on `Outcome::Incomplete`.
- **Rust control-flow sugars as ROUTERS over effects** — the `sugar/try_sugar.py::_route_incomplete` pattern: match effect vs handlers, first match reduces, no match = outcome returned unchanged; **propagation is nobody-consumed-it, never simulated control flow.**
- **Refusal corners first-class** — the finally-over-incomplete named-`RuntimeEffect` precedent.
- **`GenericBodySugar` folded** from a two-exit `Option` into the three-exit law with a recorded EUF handoff.
- **Instrument FIRST:** an effect-routing frontier auditor (control-flow constructs not yet routed), pinned red. **Exit: frontier zero for the enumerated family; a bad-twin per router.**

**Drop enters the algebra deliberately (T, #3017 justified-N/A note):** "ContextManager/FinallyFallthrough — Rust's story is Drop; Phase 2 decides how Drop enters the effect algebra deliberately." That decision is a slice here, not an afterthought.

## The spine is BUILT and green — Phase 2 is consumer wiring

Every routing decision rests on machinery that ALREADY EXISTS (merged #3210, #3017 item 5). Read it first. All under `implementations/rust/sugar-lift-rust-tests/src/sugar/` (mirrored in the extraction crate `sugar-floor-algebra/src/`).

- `raise_value.rs:6` `pub struct RaiseValue { effect: Effect }`; `from_effect(effect) -> Option<Self>` builds only for raise-like effects; `is_raise_like_effect(&Effect) -> bool`.
- `guarded_raise.rs:10` `pub struct GuardedRaise { guards: Vec<Rc<Formula>>, effect: Effect }`; `from_raise(guards, raise)`, `with_prefix(&[Rc<Formula>])` (nested-guard prefixing).
- `Effect` enum (`sugar-floor-algebra/src/lib.rs:38`): `PanicMacro{boundary}`, `LiteralPanic{boundary}`, `ControlFlow{boundary}`, `CoverageGap{boundary,reason}`. **There is NO `RaiseEffect` variant — the divergence #3210 flagged; Phase 2's typed effect family closes it.**
- `Desugared` (`lib.rs:46`) carries `StmtRaise(RaiseValue)`, `StmtGuardedRaise(GuardedRaise)`, `StmtBlock { guarded, raises: Vec<GuardedRaise>, fall_through }` — raises are first-class block-interior data.
- `route_raises_operation.rs` — the closed-visitor form of the Python op: `trait RouteRaiseHandler { fn matches(&self, &Effect) -> bool; fn reduce(&self, &TemporalScope, &Effect) -> Outcome; }` (`:20`); `trait RouteRaisesVisitor { visit_stmt_raise/visit_stmt_guarded_raise/visit_stmt_block/visit_non_raise_route }` (`:25`); `RouteRaisesOperation<'a>{ handlers, owner }` (`:60`), whose `visit_stmt_block:86` routes each raise and accumulates `residual_raises`, and whose `visit_non_raise_route:111` REFUSES with `Effect::ControlFlow` (loud, never dropped).

**Everything is `pub(crate)` with only in-crate `#[test]` callers** (`route_raises_operation.rs:285/311/329`, `block_sugar.rs:304/466`). No lifter/contract consumer calls it. `floor_projection_gate.rs:48-49,90` already carries an auditor entry expecting raise floors to route through `RouteRaisesOperation` — the seed frontier instrument.

### The Python `TrySugar` reference (what Phase 2 mirrors)

`sugar/try_sugar.py` routes on TWO frontiers:
- **Incomplete frontier** — `_route_incomplete:97`: `effect = outcome.effect; if not isinstance(effect, RaiseEffect): return outcome` (propagate unchanged); `for handler in self.handlers: if handler.matches(effect): return handler.reduce(ctx, effect)` (first match reduces); else `return outcome` (nobody consumed it).
- **Block-interior frontier** — `_try_exit:76` drives `perform_operation(method_name="route_raises_with", operation=RouteRaisesOperation(self.handlers, ...))` over a `BlockValue`; `operations/route_raises_operation.py::route_block_raises` walks statements, extracts `(effect, scope)` from `RaiseValue`/`GuardedRaise`, pulls guards from `GuardedRaise`, matches handlers, and re-guards handler output by `_guard_conjunction`.

### The consumers today — NOT routed

- **`?` / try:** `sugar-walk/src/emit.rs:1343` `Expr::Try(t) => Ok(AlgebraTerm::op("try", vec![lower_expr_to_value_term(&t.expr)?]))` — lowered to an OPAQUE `op("try", [inner])` term: not refused, not routed, no effect/handler semantics.
- **panic / early-return:** `sugar-walk/src/lift.rs` recognizes `if cond { panic!() }` structurally and lifts it as a negated-condition precondition (`collect_statement_guarded_panic_effects:1915`, `wrap_branch_guard`, `panic_freedom::*` guard heads `:660-704`). This NEVER touches `Effect`/`RouteRaisesOperation`. The module doc (`lift.rs:25`) names **"early-return patterns beyond `panic!`" as NOT-YET-handled.**
- **Drop:** not in the effect algebra at all.
- There is **no `try_sugar.rs`** in the Rust kit (`try_from.rs`/`try_map.rs`/… are Result-conversion sugars, unrelated). The Rust `TrySugar`-equivalent router is what Phase 2 builds.

## FOUNDATIONAL TENSION — flagged up front, resolution proposed (coordinator/T to confirm)

#3025's deliverable literally names "wire the two real consumers — `emit.rs:1343` and `lift.rs`." But those consumers are **`sugar-walk` IrTerm-side**, and routing an `IrTerm` construct through the `Rc<Term>`/floor spine requires the term-representation BOUNDARY — which is exactly what irterm-boundary **Slice 6 (#3196)** does, and #3196 is **blocked on #3025**. Wiring `sugar-walk` directly inside Phase 2 would either (a) pull the boundary conversion into Phase 2 (duplicating #3192/#3196 and creating a dependency cycle), or (b) leave Phase 2 unable to reach its own frontier zero.

**Proposed resolution (recommended; keeps the dependency acyclic):** Phase 2 owns the ALGEBRA side and stops at the crate boundary — it (1) adds the typed effect family, (2) builds the `TrySugar`-equivalent router, (3) EXPOSES the spine as a reachable `pub` API (promoting it out of `pub(crate)`, reusing the `sugar-floor-algebra` extraction the irterm campaign already stood up), and (4) wires the consumers reachable ON THE ALGEBRA SIDE (the `Rc<Term>`/floor-level control-flow sugars in `sugar-lift-rust-tests`). The `sugar-walk` `IrTerm` rewrites of `emit.rs:1343` (`op("try")`) and `lift.rs` (panic/early-return) are routed by **irterm-boundary Slice 6 (#3196) THROUGH the boundary INTO Phase 2's now-exposed spine** — #3196 becomes a genuine consumer of what Phase 2 exposes. Phase 2's frontier auditor therefore enumerates the ALGEBRA-side control-flow constructs + "the spine is not yet a reachable consumer API"; the `sugar-walk` IrTerm frontier stays #3196's (via irterm Instrument C). This makes the #3025→#3196 dependency clean: Phase 2 builds+exposes, #3196 routes `sugar-walk` in. **If instead T wants Phase 2 to own the `sugar-walk` wiring end-to-end, Phase 2 absorbs irterm Slice 2's reachability work and #3196 collapses into it — a scope call for T.** The plan below assumes the recommended split; the coordinator should confirm before Slice 1 dispatches.

## Campaign law

1. **Instruments before drains.** The effect-routing frontier auditor + the byte-compat harness land RED/measuring before any router wires a consumer.
2. **Red-first every slice.** A compile seam (a consumer that cannot yet reach the exposed spine) or a frontier auditor row is a valid red-first transcript; a green-by-accident wiring is not.
3. **The panic is sacred; never suppress the floor.** `visit_non_raise_route`'s `Effect::ControlFlow` refusal and residual-raise formula refusal (`block_stmt_to_formula -> None`) are honest floors. No slice turns an unrouted raise into a silent drop or a simulated branch. Propagation is "nobody consumed it", explicit.
4. **Byte-compat is the acceptance bar every slice.** Baseline-vs-changed binary on the verify/emit fixtures; `cmp` + SHA. Zero drift, or a soundness issue is filed and accepted first. Wiring a router must not change emitted bytes for a construct that already lifted (e.g. `if cond { panic!() }` stays byte-identical when it routes through the spine instead of `wrap_branch_guard`).
5. **Mirror the Python reference, do not reinvent.** The router IS `_route_incomplete` + `route_raises_with`; the effect family IS `RaiseEffect`. Divergence from the reference is a soundness question, flagged, not a silent design choice.
6. **Law 8 (grab the type system).** The router is a closed-visitor operation (rustc totality); the frontier auditor is scaffolding that retires when the frontier hits zero and the exposed-API + closed-visitor totality hold the line. Prefer the fix that makes an unrouted control-flow construct unrepresentable over the fix that detects it.

## Instruments

### Instrument A — effect-routing frontier auditor (#3025's named instrument)
Enumerate every algebra-side control-flow construct NOT yet routed through `RouteRaisesOperation` (the enumerated family: `?`, `panic!`, early-return, Drop), plus "the spine is `pub(crate)`, unreachable by any consumer". Report `R(control-flow-constructs-unrouted)`, printing each with its router replacement. Pin RED in Slice 1. **Law-8 annotation: justification (b) — watches drain progress; retires when `R=0` and the closed-visitor router + exposed API make an unrouted construct a compile/type fact rather than an audited one.** Coordinate with `floor_projection_gate.rs:48-49` (the existing raise-routing auditor entry — share the predicate, do not double-count).

### Instrument B — byte-compat harness
Per implementation slice: baseline-vs-changed binary on the verify/emit fixture corpus + the panic unit tests (`lift.rs:4347 lifts_if_then_panic_as_negated_condition`, `:5612 match_arm_guarded_panic_effect_is_collected`); `cmp` + SHA. `R(byte-drift)` starts 0, stays 0. **Law-8: justification (b), permanent — observable-output equality is the soundness floor; no retirement.**

### Instrument C — TrySugar sugar-witness pair (the acceptance test, from the sugar-witness campaign)
The Rust `TrySugar`-equivalent's truthful/lying witness pair (sugar-witness campaign, #3282-#3285) IS Phase 2's acceptance test: the **lying twin going UNSAT through the production lift→compile→solve pipeline proves the routing actually works** (a raise that should propagate to an uncaught Err makes the contract UNSAT; a caught raise discharges SAT). Each router lands with its witness pair as the bad-twin. **Law-8: justification (b), permanent — the solver verdict is irreducible, exactly as the vocab/witness Instrument C.**

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(control-flow-constructs-unrouted)` | Slice 1 pins RED (the enumerated family: `?`/panic/early-return/Drop + `pub(crate)` unreachable spine). | 0 at close (each router removes one). |
| `R(spine-pub-crate-unreachable)` | 1 (the whole spine is `pub(crate)`, only test callers). | 0 after the exposure slice. |
| `R(effect-family-missing-raise)` | 1 (no `RaiseEffect` variant; `PanicMacro`/`LiteralPanic`/`ControlFlow` ununified for routing). | 0 after the effect-family slice. |
| `R(genericbodysugar-two-exit-option)` | 1 (two-exit `Option`, no three-exit law / EUF handoff). | 0 after the fold. |
| `R(byte-drift)` | 0. | Must stay 0 unless a soundness issue is filed and accepted. |
| `R(routers-without-witness-bad-twin)` | Slice 1 measures. | 0 (a bad-twin per router, verdict via the real solver). |

## Slices

### Slice 0 — Plan PR
Land this document. Post the #3025 comment (the resolution of the foundational tension) and cross-link #3196 and the sugar-witness campaign.
Exit: merged as "Part 1 of #3025 (Phase 2 effect-routers campaign plan)".

### Slice 1 — Instruments (frontier auditor + byte-compat harness + witness-bad-twin registry), RED/measuring
Land Instrument A (effect-routing frontier auditor, coordinated with `floor_projection_gate.rs`), Instrument B (byte-compat harness), and the witness-bad-twin registry (Instrument C's hook). Run RED against main; pin every vector. No production routing.
- Red-first: the auditor names each unrouted construct (`emit.rs:1343 op("try")`, `lift.rs` panic path, early-return, Drop) and the `pub(crate)` spine with its router replacement; a planted routed-construct turns its row green.
- Bad-twins: (a) a routed raise (in-crate test) is NOT flagged; (b) the opaque `op("try")` IS flagged; (c) byte-compat harness reds on a planted emitted-byte change.
Exit: three instruments measuring; every vector pinned; the enumerated family named with router replacements.

### Slice 2 — The typed effect family (`RaiseEffect`) + `GenericBodySugar` three-exit fold
Add the `RaiseEffect`-equivalent typed effect family to `Effect` on `Outcome::Incomplete` (unifying `panic`/`Result`-`Err`/early-return for routing; decide whether `PanicMacro`/`LiteralPanic`/`ControlFlow` become cases of it or route-compatible siblings — mirror the Python `RaiseEffect`, flag any divergence). Fold `GenericBodySugar` from its two-exit `Option` into the three-exit law with a recorded EUF handoff.
- Red-first: a routing unit test that needs a `RaiseEffect` the enum cannot yet express.
- Bad-twins: (a) a `panic` effect and a `Result`-`Err` effect both recognized as raise-like by `is_raise_like_effect`; (b) `GenericBodySugar`'s third exit records the EUF handoff (was silently dropped as the `None` arm); (c) a non-raise effect (e.g. `CoverageGap`) is NOT raise-like and propagates unchanged.
Exit: `R(effect-family-missing-raise)=0`, `R(genericbodysugar-two-exit-option)=0`; byte-drift 0.

### Slice 3 — The Rust `TrySugar`-equivalent router + expose the spine (`pub` API)
Build the router mirroring `_route_incomplete` (match effect vs handlers, first-match-reduces, no-match-propagates-unchanged) plus the block-interior `route_raises_with` path (already in `route_raises_operation.rs`, exercise it from the router). Promote the spine (`RouteRaiseHandler`, `RouteRaisesVisitor`, `RouteRaisesOperation`, `RaiseValue`, `GuardedRaise`) from `pub(crate)` to a reachable `pub` API in `sugar-floor-algebra` (the extraction crate the irterm campaign stood up) — this is the reachability irterm Slice 6 will consume.
- Red-first: a consumer that names the router API before it is `pub` (compile seam).
- Bad-twins (per the acceptance coupling): (a) a raise caught by a matching handler reduces (truthful → SAT); (b) a raise with no matching handler propagates the outcome unchanged (uncaught → the lying twin's UNSAT); (c) a raise under an inner `if` is caught by a wrapping handler via the block-interior path (GuardedRaise re-guarded).
Exit: `R(spine-pub-crate-unreachable)=0`; the router exists and routes both frontiers; byte-drift 0.

### Slice 4 — Wire the algebra-side `?` consumer through the router
Route the algebra-side `?`/try construct through the router instead of an opaque term. (The `sugar-walk` `emit.rs:1343` `op("try")` IrTerm rewrite is #3196's, through the boundary into this router — see the foundational-tension resolution; this slice wires the `Rc<Term>`/floor-level `?` reachable without the boundary.)
- Bad-twins: (a) `x?` whose `Ok` path discharges → SAT; (b) `x?` that propagates `Err` to an uncaught boundary → UNSAT (lying twin); (c) `x?` caught by a wrapping handler → routed, SAT.
- Byte-compat: `?` constructs that already lifted stay byte-identical.
Exit: the `?` family routes through the spine on the algebra side; `R(control-flow-constructs-unrouted)` down by `?`.

### Slice 5 — Wire panic + early-return through the router
Route the algebra-side `panic!` and early-return (currently structural guard synthesis / unhandled) through the effect family + router. Early-return beyond `panic!` (named NOT-YET-handled at `lift.rs:25`) becomes a routed `RaiseEffect`, not a dropped construct. Keep `if cond { panic!() }` byte-identical (it routes to the same negated-condition precondition through the spine).
- Bad-twins: (a) `if cond { panic!() }` → byte-identical negated-condition precondition, now via the spine; (b) an early `return v` in a branch routes as a raise-like exit and discharges/UNSATs correctly; (c) an uncaught panic propagates as a residual effect (refuses formula emission, never a silent branch).
Exit: panic + early-return route through the spine; `R(control-flow-constructs-unrouted)` down by both; byte-drift 0 on the panic fixtures.

### Slice 6 — Drop enters the effect algebra; refusal corners first-class
Make the deliberate decision (#3017): how Drop/finally-fallthrough enters the effect algebra — a named `RuntimeEffect` for finally-over-incomplete (the refusal corner made first-class), routed or refused explicitly, never simulated.
- Bad-twins: (a) a Drop with observable effect enters as a named effect and routes/refuses loudly; (b) a finally-over-incomplete refuses with the named `RuntimeEffect` (not a swallowed exit); (c) a no-op Drop does not perturb emitted bytes.
Exit: Drop is in the algebra deliberately; refusal corners are named first-class effects; byte-drift 0.

### Slice 7 — Close: frontier zero; arm the auditor as a gate; unblock #3196
Drive Instrument A to zero for the enumerated algebra-side family; arm it as a gate (a new unrouted construct is a hard red). Confirm the TrySugar sugar-witness pair (Instrument C) passes through the production pipeline (lying twin UNSAT). Signal #3196 that the spine is exposed and ready to consume through the boundary.
- Red-first: the auditor gate expects zero; a planted unrouted construct reds. Structural grep: `rg -n 'op\("try"|wrap_branch_guard' ...` classified (the `sugar-walk` IrTerm hits are #3196's, on the allowlist with a stated reason).
- Bad-twin: the TrySugar lying twin goes UNSAT through `lift_file → inv_json → z3_verdict`.
Exit: `R(control-flow-constructs-unrouted)=0` (algebra side); auditor armed; #3196 unblocked.

## Sequencing with sibling campaigns

- **irterm-boundary Slice 6 (#3196) — the downstream consumer.** #3196 is BLOCKED on this campaign and consumes what Slice 3 exposes: it routes `sugar-walk`'s `IrTerm` `?`/panic (`emit.rs:1343`, `lift.rs`) THROUGH the boundary INTO Phase 2's spine. Phase 2 must NOT do the `sugar-walk` IrTerm rewrite (that re-implements raise routing over IrTerm, forbidden by #3196's own DO-NOT). #3196 → #3197 → #3198 (irterm close) → gates ProofIR-vocab Slice 9 (#3240). Phase 2 is the unblocker at the head of this chain.
- **sugar-witness campaign (#3277-#3290) — the acceptance test.** TrySugar's witness pair is Phase 2's acceptance instrument (Instrument C). The witness campaign's Rust harness (S6, #3282) is where the pair runs; Phase 2's routers are what make the lying twin actually reach UNSAT. Coordinate so TrySugar's enrollment lands with its router.
- **#3210 / #3017 item 5 — the built spine, MERGED.** Phase 2 consumes it; do not rebuild the algebra.

## Anti-goals

- **No simulated control flow.** Propagation is "nobody consumed the effect", returned unchanged — never a synthesized branch or an eager evaluation.
- **No `sugar-walk` IrTerm raise-routing rewrite.** That is #3196, through the boundary. Phase 2 exposes the spine; it does not re-implement routing over `IrTerm`.
- **No silent drop of an unrouted raise.** `visit_non_raise_route`'s `Effect::ControlFlow` refusal and residual-raise formula refusal stay loud and get more precise.
- **No byte drift.** A construct that already lifted stays byte-identical when it routes through the spine; deliberate changes file a soundness issue first.
- **No divergence from the Python reference without flagging it.** `RaiseEffect` and `_route_incomplete` are the reference; a different shape is a soundness question on the record.
- **No rebuilding the spine.** #3210 built `RaiseValue`/`GuardedRaise`/`RouteRaisesOperation`; Phase 2 wires and exposes, it does not reimplement.

## Campaign closure

1. `Outcome::Incomplete` carries a typed `RaiseEffect` family; `panic`/`Result`-`Err`/early-return/Drop each enter the effect algebra deliberately.
2. A Rust `TrySugar`-equivalent router mirrors `_route_incomplete` + `route_raises_with`; raises route on both the Incomplete and block-interior frontiers.
3. The spine is a reachable `pub` API (out of `pub(crate)`), consumed by Phase 2's algebra-side routers and ready for #3196 through the boundary.
4. `GenericBodySugar` is folded into the three-exit law with a recorded EUF handoff.
5. The effect-routing frontier auditor is armed at zero for the enumerated algebra-side family; a new unrouted construct is a hard red.
6. Byte-compat holds across every slice (`R(byte-drift)=0`); the panic fixtures are byte-identical through the spine.
7. Each router carries a witness bad-twin whose lying case goes UNSAT through the production pipeline; #3196 is unblocked.
