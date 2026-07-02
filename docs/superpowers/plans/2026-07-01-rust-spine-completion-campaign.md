# Rust Spine Completion Campaign — IDD to Δ→0

> **For agentic workers:** This is a CAMPAIGN plan (phases + ratchets), not a step-by-step task plan. Each phase gets its own task-level plan or detailed issue when dispatched. Instruments come before drains, always. The Python kit (`implementations/python/sugar-lift-py-tests/`) is the REFERENCE IMPLEMENTATION: mirror its mechanisms, do not re-derive them; confirm every ported mechanism with a bad-twin flip (break the invariant, watch the port refuse).

**Goal:** Complete the factory/sugar/floor spine in the Rust lift kit to the Python kit's discipline level, and drive Δ(Rust-constructs-outside-the-spine) → 0, with every phase held by a red-by-design instrument that can never silently regress.

**Decision of record (T, 2026-07-01):** Option B — complete the spine, don't instrument the walker architecture as an endpoint. The Python kit's floor/temporal/effect design is superior and is the target semantics. Rust needs the temporal floor medicine regardless of anything else.

## Where we actually are (measured 2026-07-01, main @ 61e6ab137)

The Rust kit is NOT greenfield. Spine inventory against the Python reference:

| Spine component | Python reference | Rust state | % |
|---|---|---|---|
| Recognizer catalog | `sugar/sugar_base.py` owns + `factory/build.py` catalog | `sugar-lift-rust-tests/src/sugar/catalog.rs` (`EXPR_CLAIMS`/`ITEM_CLAIMS`/`STMT_CLAIMS`, `ExprSugarClaim` w/ recognize + `comes_before`, `order_candidates_or_panic`) | 90 |
| Factory chokepoint | `factory/build.py` `build_node`→`_build_site`, FactoryGap on miss | `factory.rs:530 build_expr` / `:555 build_term` — "TOTAL — every shape news either a lawful sugar node or the loud factory-gap node" | 90 |
| Three-exit law | `outcome/` Complete/Incomplete + `FactoryGap` | `lib.rs:8766 enum Outcome { Complete(Desugared), Incomplete(Effect) }` + construction-law panic w/ `CoverageGapInfo` (`factory.rs:22-31`, `factory_gap_info.rs:26`) | 90 |
| Build/desugar split | `build()` composes children; `desugar()` reduces only what it was handed | recognizer-fn pattern in `factory.rs` + `trait Sugar { fn desugar(&self, ctx) -> Outcome }` (`lib.rs:8709`) | 85 |
| Totality ledger | `grammar_ledger.py` — three-status enumerated ledger, import-time RuntimeError | `tests/grammar_totality.rs` ratchet (uncovered-(kind,shape) histogram + `UNCOVERED_CEILING`), `teethed_ledger_ratchet.rs` | 65 |
| **Floor value algebra** | `floor/*.py` ~35 value classes, methods-as-operations | ad-hoc `Term`/`Desugared`/`NumericFloor` variants + visitor traits in `term_dispatch.rs`; enforcement half exists (`sugar-cli/src/floor_runtime_check.rs` wired into doctor/self_check/release_gate) but no owned value hierarchy | **55** |
| **Temporal floor** | `temporal/` — TemporalContext, perform_temporal_operation, bind/curry/rewrite ops, BoundVar scope-capture | only `sugar/temporal_read.rs` (read recognizer) + TemporalScope/Plan/Context types; NO operation family, NO owned name-time algebra | **40** |
| **Operation double-dispatch** | `operations/perform_operation.py` — open dispatch, missing method = Floor-kind FactoryGap | fixed visitor set (`accept_scalar_floor`/`accept_monadic_floor`); no open registry, no floor-gap on missing method | **35** |
| **Effect algebra** | `effect/` RaiseEffect/RuntimeEffect; TrySugar routes effects as values (`sugar/try_sugar.py` `_route_incomplete`); propagation = nobody consumed the effect | `Outcome::Incomplete(Effect)` exists; no RaiseEffect-style typed effect family, no TrySugar-equivalent router for `?`/panic/early-return | **~35** |

**The anti-spine (demolition targets):**
- `sugar-walk/src/lift.rs` — 5,133 lines of hand-rolled match-ladder walkers (`lift_tail_expr_to_result_term`, `lift_predicate_inner`, `wrap_branch_guard`, …) duplicating recognition the catalog owns. This is where the #2997 silent-drop frontier offenders concentrate.
- Three parallel recognizer/dispatch worlds: the fine node catalog (`sugar-lift-rust-tests/src/sugar/`), the coarse plugin tagger (`sugar-walk/src/bin/walk_rpc.rs`, 18k lines), and the RPC transport kit (`libsugar/src/core/lift_plugin.rs`). Only the first is the spine; the boundaries between the three must become explicit seams, not overlapping reimplementations.
- `GenericBodySugar` (`generic_body_sugar.rs`) returns two-exit `Option<Rc<Formula>>` (Some=discharged, None=fall to EUF), sitting outside the three-exit accounting.

Note: `libsugar/src/desugar.rs`'s Refusal machinery (NonConfluent/NonTerminating/InvalidEquation/WpPreservationNotDischarged) is a DIFFERENT concern — desugaring-equation legality for the rewrite-rule engine. It stays; do not confuse it with the construct spine.

## Campaign law

1. **Instruments before drains.** No phase's drain starts until its frontier auditor is on main, red, with the R vector pinned. The instruments from the crimes board (#2997 silent-drop frontier, #2998 gate parity) are the campaign's standing acceptance harness and land first.
2. **Python is the reference.** Port mechanisms, not vibes: same three mutations for temporal, same effect-routing shape for try/raise, same base-method-gap-panics pattern for floor values. Where Rust idiom forces divergence (traits vs getattr), the DIVERGENCE gets a doc comment citing the Python file it mirrors and why the shape differs.
3. **Bad-twin confirmation.** Every ported mechanism ships with at least one discrimination test that breaks the invariant and asserts the loud refusal (per-variant discipline: positive + discrimination + structural).
4. **Ratchet in the same PR.** A drain slice that turns frontier rows green deletes those rows from the pinned expectation in the same PR. Red is honest; false green is the enemy.
5. **The panic is sacred.** No slice may convert a construct the spine doesn't own into a silent skip, a default, or a two-exit Option. Refusals are recorded (DigRefusal precedent) or raised (CoverageGapInfo), never dropped.

## Phases

### Phase 0 — Instruments (in flight on the crimes board)
- #2997: silent-drop frontier auditor over the walker crates (`_ => {}` / `_ => None` / `unwrap_or` sites, per-site sanction markers, pinned R vector). This measures the anti-spine and becomes the demolition progress meter.
- #2998: lift-ownership gate, construction-law chokepoint gate, rustfmt gate.
- Exit criterion: both on main, red with pinned vectors, in CI.

### Phase 1 — Floor value algebra (55% → 100%)
Build the owned FloorValue hierarchy, porting `floor/*.py`:
- `trait FloorValue` with the projection law from the Python Task-7 fix: `to_term(owner)` default implementation raises the Floor-kind gap ("write more Floor: implement <T>.to_term"); each concrete floor value owns its projection. Rust idiom: default trait method returning `Err(CoverageGap)` — never a blanket impl that succeeds.
- Concrete values mirroring the Python set where Rust semantics need them (TermValue, BoolValue, StringValue, SymbolicValue, ArrayLiteral, TupleValue, SliceValue, ObjectValue, BlockValue, ReturnValue, BoundVar, …). Enumerate by grepping the Python `floor/__init__.py` export list and mapping each to needed-now / not-yet-Rust-relevant (with reasons).
- **Open operation dispatch** replacing the fixed visitor set: `perform_operation(owner, blame, receiver, method, operation, ctx)` mirror. Rust cannot getattr; the port is a small method-table/enum-dispatch on the FloorValue trait where a missing arm returns the Floor-kind gap carrying owner/blame/fix — the SHAPE that matters is "missing method = loud gap naming the write-more-Floor fix", not the reflection.
- Instrument: floor-projection gate (no isinstance/match-ladder over floor types outside the floor module — the Rust twin of Python's ladder gate) + extend `floor_runtime_check.rs` signals to count algebra gaps.
- Exit: term_dispatch.rs visitor traits deprecated in favor of the algebra; ladder gate green; bad-twin per value type.

### Phase 2 — Effect algebra + control-flow routers (35% → 100%)
Port the effect family and the TrySugar design:
- Typed effects: `RaiseEffect`-equivalent for panics/Result-Err/early-return; `Outcome::Incomplete(Effect)` gains the typed family (today Effect is opaque). Propagation stays "nobody consumed it" — no control-flow simulation anywhere.
- Rust control-flow sugars as routers over effects: `?` operator, `panic!`/unwrap sites, early return, and (the TrySugar twin) match-on-Result routing. The router pattern is `sugar/try_sugar.py:_route_incomplete`: match effect against handlers, first match reduces, no match returns the outcome unchanged.
- Refusal corners come first-class from day one: the finally-over-incomplete precedent — where a shape's join semantics aren't built yet, return a NAMED RuntimeEffect describing the missing join, never approximate.
- Fold `GenericBodySugar` into the three-exit law: `Option` return becomes `Outcome`, its None-falls-to-EUF becomes an explicit recorded handoff so encoder discharge participates in Complete/Incomplete/Gap accounting.
- Instrument: effect-routing frontier — auditor listing control-flow constructs (try-equivalent, `?`, panic sites, loops w/ break-value) not yet routed through effect algebra; pinned, red.
- Exit: frontier zero for the enumerated construct family; bad-twins (unmatched effect propagates; matched effect reduces handler body; refusal corner returns named effect).

### Phase 3 — Temporal floor (40% → 100%)  [MANDATORY regardless of other phases — T, 2026-07-01]
Port `temporal/` mechanism-for-mechanism:
- `TemporalContext` as immutable binding tuple; rebind = drop-prior + append-fresh; `value_for` reverse-scan as THE ONLY name resolution; miss = Floor-kind gap.
- Exactly three mutations — bind / curry / rewrite — routed through a `perform_temporal_operation` mirror; missing method = gap naming "route this through the temporal floor".
- Scope-captured lazy aliasing: the BoundVar pattern (name aliases unreduced source + definition scope; reference recomposes against the captured scope; `x = x + 1` terminates by construction). Map onto Rust's shadowing/mut semantics: shadowing = rebind; `mut` assignment = rewrite; closures = curry. The `let y=x(); assert(y)` desugaring doctrine (SSA-correct let-collapse) rides on this floor.
- **Design question to resolve in-phase, flagged not assumed:** AST-lift vs LLBC/MIR path. MIR already has SSA-like discipline; the temporal floor likely owns the AST-lift side only, with the LLBC side proving equivalence (differential test: same source, both paths, same pinned FOL) rather than duplicating the floor. Architect sign-off required on this seam before the phase's drain begins.
- Instrument: temporal-dispatch frontier auditor, ported from `idd/collect_temporal_dispatch_frontier.py` including the direct-context-minting offender kind added in the Python Task 8.
- Exit: frontier zero; bad-twins (side-door binding flagged; stale-scope recomposition refused; curry through floor only).

### Phase 4 — Match-ladder demolition (the drain of drains)
Route `lift.rs`'s walkers through the catalog so the ladders collapse into claims:
- Slice by construct family exactly like the Python dunder campaign (tail-exprs, predicates, branch guards, loops/exceptions, patterns), one PR per family: add/extend catalog claims → route the walker path through `build_term`/`build_expr_role` → delete the ladder arms → ratchet the #2997 frontier rows out.
- The #2997 R vector is the progress meter: campaign done when lift.rs's rows hit zero and the file is a thin adapter (or gone).
- walk_rpc's coarse plugin tagger and libsugar's transport kit get explicit seam docs (what each layer owns, what it must never do) — unification into fewer layers is OUT of campaign scope unless a phase forces it; boundaries first.

### Phase 5 — Totality ledger (65% → 100%)
Promote ratchet-as-test to an enumerated ledger:
- `grammar_ledger` twin over syn node kinds (and the LLBC node universe separately): every (kind, shape) classified lifted / debt / membrane; a syn version bump introducing new variants = loud failure at ledger-check time (the Rust substitute for Python's import-time RuntimeError, since #[non_exhaustive] hides new variants from the compiler).
- Existing `grammar_totality.rs` histogram becomes the ledger's census input; `UNCOVERED_CEILING` is replaced by exact classification (ceiling-style ratchets tolerate churn inside the budget — the ledger does not).
- Exit: Δ(unclassified syn constructs) = 0 with the debt list pinned; dunder-frontier-style drains for the debt families follow as post-campaign issues.

## Dogfood closure criterion
The campaign is DONE when, on the repo's own Rust sources (self-application via cmd_self_check):
1. #2997 frontier = 0 (no silent drops in the lift path),
2. effect-routing frontier = 0 for the enumerated construct family,
3. temporal-dispatch frontier = 0,
4. ledger has no unclassified constructs (debt is named, membrane is argued),
5. floor_runtime_check hard signals all green at ReleaseGate mode,
and every per-PR expected-K-and-Δ matrix during the campaign showed Δ(unproven, new) = 0 — new constructs land already-owned or loudly-refused, never silently.

## Sequencing vs the crimes board
Crimes board (#2981-#3001) finishes first — the fleet is on it. Phase 0's instruments ARE board items (#2997/#2998). Phases 1-2 can start as soon as Phase 0 lands even if stragglers remain on the board; Phase 3 (temporal) is independent of 1-2 and can run parallel with its own worker once the Phase-0 instruments exist; Phase 4 depends on 1-3 (the ladders route into the completed spine, not around it); Phase 5 can start any time after Phase 0 (ledger measures, doesn't depend).

## Anti-goals (say no to these during the campaign)
- No new bespoke annotation/DSL surface; lift NATIVE Rust only.
- No solver in the lift (gate from #2998 enforces).
- No unification mega-refactor of the three dispatch worlds "while we're in there" — seams and boundaries, then targeted collapse per phase need.
- No ceiling-style tolerances in new instruments — exact pinned vectors only.
- No porting Python's reflection dispatch literally; port the LAW (missing method = loud gap with fix) in Rust idiom.
