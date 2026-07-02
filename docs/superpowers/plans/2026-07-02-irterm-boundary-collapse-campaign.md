# IrTerm Boundary-Collapse Campaign - IDD Plan

> **For agentic workers.** This is a CAMPAIGN, not a patch. The coordinator dispatches ONE slice at a time; do not open the next slice until the prior slice's issue is merged and its exit criteria are green. **Byte-compatibility of emitted contract/verifier output is the acceptance bar on EVERY implementation slice** — a slice that changes a single emitted byte without a separately filed and accepted soundness issue has failed, regardless of what it "cleaned up". You are hardening soundness-adjacent code (`sugar-walk` contract emission has been hardened all week); move like it. Read `AGENTS.md` (the IDD manifesto and the enforcement ladder) and `SHARED-LANGUAGE.md` (lift/lower 2×2, Boundary, Contract) before your first line of code. Option A is DECIDED (below); do not relitigate it — implement it.

## The decision of record (T Savo, 2026-07-02 — collapse, do not relitigate)

**Option A — ONE REPRESENTATION.** The contract layer (`sugar-walk`, which speaks `IrTerm`) converts to the algebra's term representation (`Rc<Term>` — the closed-visitor floor/operation world) **at its boundary**. `IrTerm` becomes a serialization/interface detail at the edge, not a parallel dispatch representation that the lifter reasons over structurally. The algebra's `Rc<Term>` + closed visitors is the **single dispatch world**; every floor and every operation is reachable from the contract layer through **one conversion at the boundary**, never through a second per-operation adapter. This rhymes with factory-or-side-door and with the mini-interpreter deletion (#3150): kill the parallel representation, do not bridge it permanently.

**Why NOT Option B** (a permanent `IrTerm`-facing adapter that round-trips per call, e.g. re-implementing `accept_control_flow_guard`'s logic over `IrTerm`): two representations forever, one new adapter arm per new operation, and a standing side-door temptation every time an operation is added. Rejected. The `GuardedReturnTerm` / `SymbolicValueTerm` / `wrap_branch_guard` shapes in `lift.rs` (below) ARE Option B in embryo — the campaign deletes them.

**What "the boundary" is, concretely.** The conversion is not hypothetical: `sugar-ir-symbolic/src/convert.rs` already carries `term_from_ir(ir::Term) -> Term` (`convert.rs:150`), `term_to_ir(&Term) -> ir::Term` (`convert.rs:123`), and their `formula_*`/`binding_*` siblings (`convert.rs:210`/`:261`/`:192`/`:199`). `IrTerm` (`sugar-ir-types/src/lib.rs:342`) and `sugar_ir_symbolic::Term` (`sugar-ir-symbolic/src/lib.rs:106`) are the **same five variants** (`Var`/`Const`/`Ctor`/`Lambda`/`Let`). So the lowering `IrTerm -> Rc<Term>` is already written and total-by-shape; the raising `Rc<Term> -> IrTerm` likewise. The campaign is therefore a WIRING campaign (reach the conversion, route through the algebra, delete the duplicates), not a "write a converter" campaign. The one thing that is NOT free is reachability — see "Current measured shape".

## Foundations already laid (#3017 items 1–4, merged; item 3 deliberately UNWIRED)

- `GuardedReturn` floor + guard-composition protocol (#3017 item 1).
- `SymbolicValue` floor — sort-neutral wrapper over `Term::Var` (#3017 item 2).
- `ControlFlowGuardOperation` as a dispatched operation over the algebra (`sugar-lift-rust-tests/src/sugar/control_flow_guard_operation.rs`), #3017 item 3. Its module header says it out loud (`control_flow_guard_operation.rs:11-14`): *"this module consumes `Rc<Formula>` guards and `Rc<Term>` statement floors. It does NOT cross into `sugar-walk`'s `IrTerm` branch-guard construction (`wrap_branch_guard`); the campaign plan reserves that type convergence / generated-dispatch decision for Phase 4."* **This campaign is that Phase-4 decision made and executed. `ControlFlowGuardOperation` is the first wired consumer of the boundary.**
- `BoundVar` floor — recomposable `(name, source_body, definition_scope)` (#3017 item 4).

These operations exist in the algebra and are exercised only by in-crate callers (`guard_exit`/`guard_block`, `control_flow_guard_operation.rs:116`/`:130`). The contract layer cannot call them today. This campaign wires them.

## Current measured shape: two term worlds and where they meet

**World 1 — `IrTerm` (serialization IR).** `sugar-ir-types/src/lib.rs:342`, five serde-tagged variants (`var`/`const`/`ctor`/`lambda`/`let`). This is the on-wire / interface shape. `sugar-walk` speaks ONLY this: `lift.rs`, `walk.rs`, `marriage.rs`, `wp.rs`, `llbc_lift.rs`, `walk_rpc.rs` construct and match `IrTerm` throughout.

**World 2 — `Rc<Term>` + closed floor visitors (the algebra).** `sugar_ir_symbolic::Term` (`sugar-ir-symbolic/src/lib.rs:106`) is the term; the floor algebra (`Desugared` enum `sugar-lift-rust-tests/src/lib.rs:8619`, the `ControlFlowGuardVisitor`/`MonadicFloorVisitor`/`SymbolicValueFloorVisitor` closed traits in `sugar-lift-rust-tests/src/sugar/term_dispatch.rs`, and the operations that dispatch over them) is the single lawful dispatch world. Adding a floor kind makes every operation that fails to handle it a compile error — totality by construction (the enforcement-ladder endgame the manifesto names).

**What `sugar-walk` reasons over structurally today (the Option-B-in-embryo sites — these are the drain).** All in `sugar-walk/src/lift.rs` unless noted:

- `guarded_return_for_branch` (`lift.rs:721`) + its test-only alias `wrap_branch_guard` (`lift.rs:717`) — re-implements `ControlFlowGuardOperation`'s guard-prefix composition over `IrTerm`, structurally matching `IrTerm::Ctor` heads. **This is the exact function #3017 item 3 pointed at.**
- `GuardedReturnTerm` (`lift.rs:639`, `into_value` `:644`) — an `IrTerm`-side duplicate of the `GuardedReturn` floor.
- `SymbolicValueTerm` (`lift.rs:609`, `into_term` `:613`) + `symbolic_cf_ite` (`lift.rs:618`) — an `IrTerm`-side duplicate of the `SymbolicValue` floor; the module comment (`lift.rs:606`) itself says *"`sugar-walk` uses `IrTerm` rather than the floor algebra's `Term`, so this adapter keeps the v1 wire shape byte-identical while naming that sort-neutral boundary."* That comment is the confession this campaign discharges.
- `len_eq_one_branch_guard` (`lift.rs:759`), `find_next_partial_receiver` (`lift.rs:785`), `len_receiver_term` (`lift.rs:1203`), `wrap_cf_guarded` (`lift.rs:1862`), `wrap_known_option_unwrap_guard` (`lift.rs:1852`) — structural `IrTerm::Ctor` walking for guard synthesis.
- `lift_tail_expr_to_result_term` (`lift.rs:548`) / `lift_tail_if_to_ite_term` (`lift.rs:555`, guard reconstruction `:598-600`) — the tail-expr → result-term family (#3027 tail-exprs / branch-guards).
- `lift_predicate_inner` (~`lift.rs:1659`) — predicate/raw-term distinction re-derived structurally (#3017 item 8 `PredicateValue`).
- `collect_pat_bindings` (`walk.rs:581`) + the `Pat::Tuple`/`TupleStruct`/`Struct`/`Slice` projection ladders — the pattern family (#3027 patterns).

**Where the two worlds meet today: NOWHERE at the operation level.** They meet only at the shared *shape* (both enums are Var/Const/Ctor/Lambda/Let), and only inside `sugar-ir-symbolic::convert`. `sugar-walk` never calls `convert`. That is the whole problem: the contract layer maintains a second, structurally-reasoned `IrTerm` world *because it has no route into the algebra*.

**The reachability wall (the load-bearing constraint every slice inherits).** `sugar-walk/Cargo.toml` depends on `sugar-ir-types`, `sugar-lift-contracts`, `sugar-canonicalizer`, `libsugar` — **NOT** `sugar-ir-symbolic` (where `convert` lives) and **NOT** `sugar-lift-rust-tests` (where the algebra lives). Worse, `ControlFlowGuardOperation`, `GuardedReturn`, `SymbolicValue`, and `Desugared` are `pub(crate)` inside `sugar-lift-rust-tests` — a `-tests` crate, not a library API. **So Option A's "convert at the boundary" is trivially reachable for `Rc<Term>` (add the `sugar-ir-symbolic` dep, call `term_from_ir`) but the OPERATIONS are not reachable at all without promoting the floor algebra into a shared library crate.** This is the one place the two worlds cannot be joined without new plumbing, and it is Slice 2. Everything downstream depends on it.

## The boundary design

**Where the single conversion lives.** A new module `sugar-walk/src/term_boundary.rs` owns exactly two thin wrappers at the contract-layer edge:

- `lower_ir(&IrTerm) -> Rc<Term>` and `lower_ir_formula(&IrFormula) -> Rc<Formula>` — the IrTerm→algebra lowering, delegating to `sugar_ir_symbolic::convert::term_from_ir` / `formula_from_ir`. Called once when a contract-layer walker crosses into the algebra to compose.
- `raise_ir(&Rc<Term>) -> IrTerm` and `raise_ir_formula(&Rc<Formula>) -> IrFormula` — the algebra→IrTerm raising for whatever must round-trip back for wire emission / serialization, delegating to `term_to_ir` / `formula_to_ir`.

No other module in `sugar-walk` is permitted to convert; no operation gets its own adapter. This is the single conversion the decision names.

**The totality obligation (a lift/lower fidelity claim — it gets its own instrument).** The lowering must be TOTAL over every `IrTerm` the contract layer can produce, or REFUSE LOUDLY — never a silent lossy drop. Two facts anchor this:

1. `IrTerm ↔ Term` is total by shape (five identical variants), so `lower_ir` never silently drops a term-level node.
2. The one existing loud-refusal seam is `From<ir::Sort> for Sort` (`convert.rs:~34`), which `unimplemented!()`s on `Sort::Function`/`Dependent`/`Region` (deferred to #331/#332/#401). That refusal is CORRECT under doctrine (loudly lossy, never silently lossy) and is the pinned discrimination case for the totality instrument. `raise_ir` inherits the same obligation: any algebra construct with no `IrTerm` wire form must `panic!`/`Err` loudly, not emit a degraded term.

The totality instrument (Instrument A) pins this as a property/ratchet: round-trip fidelity on a term corpus, plus a refusal ledger that must fire on the known-lossy inputs.

**How `ControlFlowGuardOperation` becomes the first wired consumer.** Today `lift_tail_if_to_ite_term` does (`lift.rs:598-600`):

```
let then_term = guarded_return_for_branch(&cond_term, false, then_term).into_value();
let else_term = guarded_return_for_branch(&cond_term, true,  else_term).into_value();
Some(symbolic_cf_ite(cond_term, then_term, else_term).into_term())
```

After Slice 3 it becomes: lower `cond_term`/`then_term`/`else_term` via `lower_ir`, build the branch guards as `Rc<Formula>`, drive `ControlFlowGuardOperation::guard_exit` (the algebra op — the SAME mechanism the Python `operations/control_flow_guard_operation.py` runs), then `raise_ir` the composed exit back to the `IrTerm` the wire expects. `GuardedReturnTerm` and the `IrTerm`-side guard fold are DELETED. The emitted bytes are identical because the algebra composes the same `cf_guarded`/`cf_ite` shape — proven by the byte-compat gate, not asserted.

## Campaign law

1. **Instruments before drains.** No routing slice merges without its bad-twins landed and red-then-green: a conversion that must refuse, a walker whose catalog routing must emit byte-identically, a lossy variant that must loudly refuse (not silently drop). One per affected seam.
2. **Red-first every slice.** The first artifact is a red instrument or a compile seam, not a green diff. A compile failure from `sugar-walk` naming an algebra type it cannot yet reach is a valid red-first transcript. A green-by-accident migration is not.
3. **The panic is sacred; never suppress the floor.** `unimplemented!`/`panic!` refusals in `convert` and `ControlFlowGuardOperation`'s `visit_non_control_flow` gap are honest floors. No slice softens a refusal into a silent `return None` or a degraded term. Absent conversion is said LOUDLY.
4. **Byte-compat is the acceptance bar every slice.** Build a baseline binary from the slice's base commit, run the same verify/emit fixture with baseline and changed binaries, `cmp` + SHA the emitted JSON. Zero drift, or a soundness issue is filed and accepted before merge.
5. **Factory-or-side-door; one representation, not two.** Every composition goes through the algebra operation via the boundary. `sugar-walk` must not grow a NEW structural `IrTerm` match that duplicates an algebra floor. The anti-second-representation auditor (Instrument C) is the judge and its ratchet only moves DOWN.
6. **Ratchets move in the same PR.** A slice that deletes a structural `IrTerm`-reasoning site also tightens the auditor expectation. No slice widens the auditor allowlist to pass.
7. **Enforcement-ladder endgame.** Prefer the fix that deletes the axis over the fix that greens it. The best close is that a duplicate `IrTerm` shape becomes unrepresentable in `sugar-walk` because the only route to guard composition is the algebra.

## Instruments

### Instrument A — conversion-totality / round-trip fidelity
A property/ratchet test (`sugar-walk/tests/term_boundary_totality.rs` or in-crate `#[cfg(test)]`): over a corpus of `IrTerm`/`IrFormula` values (harvested from existing lift fixtures + hand-planted edge cases), assert `raise_ir(lower_ir(x)) == x` byte-identically, and assert a **refusal ledger**: every input class with no faithful algebra image (the `Function`/`Dependent`/`Region` sort, any future algebra-only construct) MUST make the conversion refuse loudly (caught `panic`/`Err`), counted as `R(conversion-refusals)` at a pinned expected set. A refusal that becomes a silent success is a red. Rung: test (climbing toward "the conversion cannot be bypassed" once the auditor gate arms).

### Instrument B — byte-compat of contract/verifier output
Per implementation slice: baseline-vs-changed binary on the verify/emit fixture corpus, `cmp` + SHA over emitted JSON. This is the acceptance bar for every consumer that serializes reports. `R(byte-drift)` starts 0 and must stay 0.

### Instrument C — anti-second-representation auditor
A grep/AST audit (`sugar-walk/tests/second_representation_audit.rs`) that enumerates every site in `sugar-walk` that reasons STRUCTURALLY over `IrTerm` in a way that duplicates an algebra floor/operation (the drain list above), and pins `R(structural-irterm-reasoning-sites)`. It classifies each site with its algebra replacement (`ControlFlowGuardOperation`, `SymbolicValue`, `PredicateValue`, `RouteRaisesOperation`, pattern catalog claim). The ratchet only moves DOWN; a NEW such site is a red. Rung: auditor now, promoted to a gate at close. (Pure serialization/formatting walks like `ir_term_to_text` and MIR-lowering `*_to_ir_term` constructors are NOT offenders — they cross the boundary in the sanctioned direction and are on the allowlist with a stated reason.)

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(structural-irterm-reasoning-sites)` | Pinned by Instrument C in Slice 1 (the drain list: branch-guard family, symbolic/cf_ite family, predicate, pattern ladders). | 0 at campaign close (each routing slice removes one family). |
| `R(unwired-algebra-operations-reachable-from-contract)` | `ControlFlowGuardOperation` and the `GuardedReturn`/`SymbolicValue` floors exist but are unreachable from `sugar-walk` (count = the operations #3017 items 1–4 left unwired). | 0 — every one reachable through the single boundary. |
| `R(conversion-refusals)` | Pinned set (the `Function`/`Dependent`/`Region` sort refusal) in Slice 1. | Stays at the pinned set; a DROP to 0 (silent success) or growth by silent-lossy is a red. |
| `R(byte-drift)` | 0. | Must stay 0 unless a separate soundness issue is filed and accepted. |
| `R(second-representation-adapters)` | ≥3 (`GuardedReturnTerm`, `SymbolicValueTerm`, `guarded_return_for_branch`/`wrap_branch_guard`). | 0 — all deleted, the boundary is the only route. |

## Slices

### Slice 0 — Plan PR
This document. Coordinator's; not an issue.

### Slice 1 — Instruments (totality + byte-compat harness + anti-second-representation auditor)
Land Instruments A, B, C; run RED/measuring against current main; pin every vector. No production change.
- Instrument A pins `R(conversion-refusals)` at the `Function`/`Dependent`/`Region` sort refusal and proves `raise_ir(lower_ir(x)) == x` on the fixture corpus (via a temporary test-only path into `convert`, since the `term_boundary.rs` wrappers do not exist yet — or gate this slice's A behind the Slice-2 dep and land only the corpus + refusal ledger here; coordinator's call).
- Instrument C enumerates and pins `R(structural-irterm-reasoning-sites)` with the per-site algebra replacement.
- Bad-twins: plant an `IrTerm` carrying a `Function` sort (Instrument A must refuse loudly; delete before merge); plant a new structural `IrTerm::Ctor` guard match in `sugar-walk` (Instrument C red; delete before merge).
- Exit: three instruments green/measuring; every vector pinned; the drain list named with replacements.

### Slice 2 — Boundary conversion module + algebra reachability (THE RISKY SLICE)
Make the algebra reachable and add the single conversion. NO routing yet — behavior unchanged, byte-drift trivially 0.
- Promote the floor algebra (`ControlFlowGuardOperation`, `GuardedReturn`, `SymbolicValue`, `Desugared`'s statement-composition surface, and the closed visitor traits they need) from `pub(crate)` in `sugar-lift-rust-tests` into a **shared library crate** both `sugar-lift-rust-tests` and `sugar-walk` can depend on (e.g. `sugar-floor-algebra`), OR expose the minimal `pub` surface if extraction proves too broad for one slice — coordinator decides at dispatch, but the END STATE is a library API, never `sugar-walk` depending on a `-tests` crate. This is where the two worlds physically join; treat cycle-freedom (`sugar-ir-symbolic` and the algebra lib must not depend on `sugar-walk`) as a compile gate.
- Add `sugar-walk` deps: `sugar-ir-symbolic` (for `convert`) and the algebra lib.
- Add `sugar-walk/src/term_boundary.rs`: `lower_ir`/`lower_ir_formula`/`raise_ir`/`raise_ir_formula`, thin over `convert`, with the totality obligation wired to loud refusal. Wire Instrument A through the real wrappers.
- Red-first: the compile seam (`sugar-walk` names algebra types it cannot yet reach) + Instrument A on the real wrappers.
- Bad-twins: a `raise_ir` of an algebra-only construct with no wire form must panic loudly (not emit a degraded term); the `Function`-sort lowering must refuse.
- Exit: `sugar-walk` can lower an `IrTerm`, call an algebra operation, and raise back; Instrument A green through the real path; `R(byte-drift)=0`; no dependency cycle.

### Slice 3 — Wire `ControlFlowGuardOperation` as the first consumer (branch-guard family) — the end-to-end proof
Replace the `IrTerm`-side guard composition in `lift_tail_if_to_ite_term` (`lift.rs:598-600`) and `guarded_return_for_branch` (`lift.rs:721`) with: `lower_ir` the condition/value, build guards as `Rc<Formula>`, drive `ControlFlowGuardOperation::guard_exit`, `raise_ir` the composed exit. DELETE `GuardedReturnTerm` (`lift.rs:639`) and the test-only `wrap_branch_guard` (`lift.rs:717`) once its behavior is the algebra's.
- Red-first: byte-compat harness on the branch-guard fixtures, plus the compile churn from deleting `GuardedReturnTerm`.
- Discrimination bad-twins: (a) a branch whose guard predicate the algebra does not recognize must leave the branch value UNCHANGED and carry no fact (same honest-undecidable behavior as `branch_guard_head` returning `None` today) — NOT an over-proof; (b) the `is_some`/`is_none` complement fixture must emit byte-identical `cf_guarded`/`cf_ite`; (c) a lossy sort in the condition must make `lower_ir` refuse loudly, not silently drop the guard.
- Ratchet: `R(structural-irterm-reasoning-sites)` down by the branch-guard family; `R(second-representation-adapters)` `GuardedReturnTerm` removed; `R(unwired-algebra-operations-reachable-from-contract)` `ControlFlowGuardOperation` → wired.
- Exit: branch-guard fixtures byte-identical; `GuardedReturnTerm` gone; auditor ratchet tightened.

### Slice 4 — Route the tail-expr / `cf_ite` family through the boundary (`SymbolicValue`)
Route `lift_tail_expr_to_result_term` (`lift.rs:548`), `lift_tail_if_to_ite_term`'s `symbolic_cf_ite` (`lift.rs:618`) through the `SymbolicValue` floor (#3017 item 2) via the boundary; DELETE `SymbolicValueTerm` (`lift.rs:609`) and the `IrTerm`-side `symbolic_cf_ite`.
- Red-first: byte-compat on the tail-expr / if-in-value-position fixtures.
- Bad-twins: a sort-neutral `cf_ite` over uninterpreted operands emits byte-identically (the `CF_ITE` congruence shape must survive); an operand the `SymbolicValue` floor cannot carry refuses loudly; an if-without-else `unit` ctor still discharges reflexively.
- Ratchet: tail-expr/cf_ite family out; `SymbolicValueTerm` removed.

### Slice 5 — Route the predicate family (`PredicateValue`, #3017 item 8)
Route `lift_predicate_inner` (~`lift.rs:1659`) through the boundary so the predicate/raw-term distinction is the algebra's `PredicateValue`, not a structural re-derivation. If `PredicateValue` is not yet built, this slice is BLOCKED on #3017 item 8 — flag to coordinator rather than re-deriving it in `sugar-walk`.
- Red-first: byte-compat on predicate-lift fixtures. Bad-twins: a `BoolValue`-as-term vs a `PredicateValue` must stay distinguished; a raw term routed as a predicate must refuse.
- Ratchet: predicate family out.

### Slice 6 — Route the loops/exceptions family (`RouteRaisesOperation`, #3017 item 5)
Route the raise/`?`/panic control-flow lifting through `RouteRaisesOperation` via the boundary. BLOCKED on #3017 item 5 (`RaiseValue`/`GuardedRaise`/`RouteRaisesOperation`) and Phase 2 (#3025) — this slice routes INTO that spine, it does not build it. Flag if the algebra op is absent.
- Red-first: byte-compat on try/`?`/panic-routing fixtures. Bad-twins: a raise under an inner `if` routed by a wrapping handler still composes; an uncaught raise stays a loud residual effect (never a dropped `continue`).
- Ratchet: loops/exceptions family out.

### Slice 7 — Route the pattern family (`walk.rs` `collect_pat_bindings`)
Route the `Pat::Tuple`/`TupleStruct`/`Struct`/`Slice` projection ladders (`walk.rs:581+`) through catalog claims via the boundary instead of hand-constructing `IrTerm::Ctor` projections (`tuple_proj`/`field`/`index`).
- Red-first: byte-compat on destructuring-binding fixtures. Bad-twins: a nested destructure projects byte-identically; an unsupported pattern shape refuses loudly rather than emitting a degraded projection.
- Ratchet: pattern family out.

### Slice 8 — Retire the structural sites + arm the auditor as a gate; close
With `R(structural-irterm-reasoning-sites)` at 0, promote Instrument C from a counter to a GATE (a new offender is a hard CI red), and — where the enforcement ladder allows — make the duplicate `IrTerm` guard-composition shape unrepresentable (delete the residual helpers `len_eq_one_branch_guard`/`find_next_partial_receiver`/`wrap_cf_guarded`/`wrap_known_option_unwrap_guard` if fully subsumed).
- Red-first: the auditor as a gate on a planted offender. Bad-twin: reintroduce one structural guard match; gate must fail.
- Exit: every vector at target; auditor armed; #3027 Phase 4 unblocked.

## Anti-goals

- **No permanent per-operation `IrTerm` adapter.** That is the rejected Option B. Every operation is reached through the single boundary, never a bespoke `IrTerm`-facing arm.
- **No lossy silent conversion.** A term/sort/construct with no faithful image REFUSES loudly. `R(conversion-refusals)` dropping to 0 (silent success) is a regression, not progress.
- **No changing `IrTerm`'s on-wire / serialization format.** The wire shape and CID are conserved; byte-compat is the proof.
- **No touching hash/CID/signature/JCS canonicalization.** The boundary is a term-representation move, not an anchoring change.
- **No doing all walker families in one PR.** One family per slice, each with its own byte-compat gate and bad-twins.
- **No relitigating Option A.** The decision is made. If a slice cannot proceed without a genuinely new conversion arm, that is the reachability wall (Slice 2) or a missing upstream algebra op (#3017 items) — flag to the coordinator; do not re-derive the operation over `IrTerm`.
- **No `sugar-walk` depending on a `-tests` crate.** The algebra becomes a library; the end state is a `pub` API.

## Campaign closure

CLOSED when: `R(structural-irterm-reasoning-sites) = 0`; `R(second-representation-adapters) = 0` (`GuardedReturnTerm`/`SymbolicValueTerm`/`wrap_branch_guard` deleted); `R(unwired-algebra-operations-reachable-from-contract) = 0` (`ControlFlowGuardOperation` and the #3017 floors reachable and used through the single boundary); `R(conversion-refusals)` at its pinned set (loud, never silent); `R(byte-drift) = 0` across every slice; Instrument C armed as a gate. At that point `IrTerm` is a serialization detail at the edge and `Rc<Term>` + closed visitors is the single dispatch world — Option A, realized.

**How this unblocks #3027 and feeds #3043.** #3027 (Phase 4: match-ladder demolition) names this exact seam as its PREREQUISITE architect decision (*"the IrTerm-vs-Rc<Term> seam — wrap_branch_guard re-implements accept_monadic_floor because it cannot call across the type boundary; decide ONCE before slicing"*). This campaign IS that decision, executed: with the boundary in place, #3027's per-family ladder demolition routes through `build_term`/`build_expr_role` into the algebra instead of around it, and its #3021 silent-drop frontier rows (R=401 at landing) can ratchet toward zero. #3043 (capstone) counts this campaign's closed vectors as part of the rust-spine completion conjunction.
