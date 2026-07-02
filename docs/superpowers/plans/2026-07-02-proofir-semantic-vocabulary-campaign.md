# ProofIR Semantic-Vocabulary Campaign - IDD Plan

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. Do NOT flip the emission base's return type from this document's branch, and do NOT start a site migration before the vocabulary spine (S2) exists. The coordinator dispatches slices ONE AT A TIME from current main. Instruments come before drains, every slice is red-first, and the raw `dict[str, Any]` emission path dies only after the typed vocabulary spine exists, every node class carries a solver-anchored verdict-witness pair, and the return-type flip has enumerated the whole offender set as a compiler/gate frontier. If you are handed a single slice, read the whole plan for orientation, then execute only the slice named in your task. Every protocol claim below is grounded in file:line; re-verify it against live main before you build on it. **Python kit first** (it holds ~19 of the ~24 untyped emission sites, the just-armed `floor_contract_agreement` gate, and the freshest floor-projection scar tissue from #3209/#3211); the Rust mirror is its own phase, sequenced AFTER the irterm-boundary campaign (#3191-#3198).

**Goal:** Make ProofIR the semantic carrier. Every proof-graph emission becomes a constructor call on a typed ProofIR node class that OWNS its FOL denotation, its construction well-formedness invariants, and its own sat/unsat verdict witnesses. Ill-formed FOL becomes unrepresentable at construction time (parse-don't-validate, applied to the emission side); semantics lives exactly once on the vocabulary rather than smeared across emission sites in sugars and consumers; and the proof graph becomes fully attributed so orphan formulas are inexpressible. When this campaign closes, a sugar can only be wrong by wiring the wrong ProofIR objects — a structural, diffable, twin-able error — and sugars stop knowing solver semantics entirely.

## The decision of record (T Savo, 2026-07-02 — collapse, do not relitigate)

ProofIR is the semantic carrier. Sat/unsat knowledge belongs with ProofIR, not sugar. Sugar is what turns sugar into ProofIR — syntax in, typed construction out, nothing more. The mistake to date was NOT treating ProofIR as semantic-carrying: semantics is currently smeared across emission sites in sugars/consumers, and FOL well-formedness is enforced nowhere by types. In the target state:

1. **Every ProofIR emission is a constructor call (`new`) on a specific typed ProofIR node class.** The constructor is the ONLY door into the proof graph (factory-or-side-door, applied one level down). Ill-formed/unparsable FOL is UNREPRESENTABLE — the type system screams bloody murder at construction time (parse-don't-validate, applied to the emission side).
2. **Each ProofIR node class OWNS:** (a) its FOL denotation (the formula template it instantiates), (b) its constructor well-formedness invariants, and (c) its own sat/unsat verdict witnesses — a truthful instantiation that must solve SAT and a lying twin that must solve UNSAT, run through the real solver. Semantics lives exactly once, on the vocabulary — not once per sugar.
3. **Sugars stop knowing solver semantics entirely.** A sugar's testimony becomes purely structural: "for my shape, I constructed these ProofIR objects" — checkable by dispatch/construction provenance, no solver involved. A sugar can only be wrong by wiring the wrong objects, which is a structural, diffable, twin-able error.
4. **The proof graph becomes fully attributed:** every formula fragment carries the node class (and construction site) that licensed it. Orphan formulas are inexpressible. (This subsumes the duplicate-emission bug filed as issue #3220 — two rows claiming one warrant cannot both carry valid provenance.)
5. **The anchors are external:** the AST grammar anchors sugar shapes, construction provenance anchors sugar wiring, the SMT solver anchors the ProofIR vocabulary's semantics, the vendor corpus anchors coverage. Nothing stands on our own say-so.

**Adjacent design context (recorded, NOT part of this campaign's slices).** Each sugar will eventually own shape/witness testimony (`mine()`/`near_miss()` examples generated from declared shapes); that is a SIBLING campaign, planned separately after this one lands its instruments (see "Sequencing with sibling campaigns").

**Adjacent soundness law (load-bearing — governs the #3220 subsumption).** The two emission paths at `_emit_euf_fact` are NOT redundant by design. The vendor/bridge-chain path swears the vendor's STATED rhs (`call:h()==42` from the source assertion); the demanded-floor path swears OUR DERIVED floor (whatever `force_floor` slams to). They coincide only when the vendor is truthful. When the vendor lies, one says `==42`, the other `==0`, both under the same `#euf#` key → conjunction → UNSAT. **That conjunction IS the stated-vs-derived lie-catching mechanism.** Therefore: dedup by `(name, IDENTICAL formula, distinct provenance)` is sound (collapses the truthful-case duplicate to one node bearing two warrants); "skip the stated emission when the demanded-floor already swore the key" is UNSOUND — it drops the differing stated fact in the lying case and destroys the UNSAT. The `EqualityFact` node carries `Provenance = Stated(vendor_locus) | Derived(floor_provenance)` as part of the node; "same key, same formula, different provenance" legally collapses to one node with two warrants, while "same key, different formula" remains two nodes the solver judges. The attributed graph makes the #3220 fix correct by construction, not by care.

## The emission surface today (typed core, untyped door)

Every protocol claim below rests on machinery that ALREADY EXISTS. Read it before designing on top of it. All Python paths are under `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/`.

### The spine is typed end-to-end, then flattened at one door

The reduction algebra is typed. `outcome/complete.py:8` `Complete{value: FloorValue}` carries a typed floor; `outcome/incomplete.py:6` `Incomplete{effect: object}` carries a refusal effect (the one Python soft spot — `object`, weaker than Rust's typed `Effect`, see below). The floors (`floor/floor_value.py:4` base + concrete `TermValue`/`BoolValue`/`CallSiteValue`/`ArrayLiteral`/`PredicateValue`/`SymbolicValue`/`ReturnValue`/`BlockValue`) are typed. The projection consumer seat exists and is typed: `operations/callsite_projection_operation.py:12` `CallsiteProjectionOperation`, whose arms each return a typed `Formula` (`project_callsite -> eq(call_term(), receiver.term)` `:22`, `project_literal` `:18`, `project_symbolic -> None` `:26`, `project_unknown -> floor-gap` `:52`). It landed via PRs #3209 (block-body force_floor) and #3211 (consumer migration). The ProofIR term/formula core is fully typed: `ir.py` frozen dataclasses `_Var/_ConstInt/_ConstStr/_ConstBool/_ConstReal/_Ctor` (`Term`), `_Atomic/_Connective/_Quantifier` (`Formula`), `PrimitiveSort/FunctionSort/DependentSort/RegionSort`, plus `ContractDecl`, `BridgeDecl` (`ir.py:511`), `CallEdgeDecl` (`ir.py:642`).

**Where the types are thrown away: the DTO door.** `factory/literal_call_report.py:744` `_emit_euf_fact` ("the SINGLE emitter") builds a typed `AssertionFactStrategy` (`:764`) and a typed `Formula` (`fact.fact_formula()`), then FLATTENS it: `:774` `inv = _formula_to_rpc(fact.fact_formula())` where `_formula_to_rpc` (`:1769`) is `json.loads(encode_jcs(formula_to_value(formula)))` — a raw `dict[str, Any]`. The `BodyUniverseDto` (`body_universe_dto.py:15-17`) then STORES `pre/post/inv: dict[str, Any] | None` — the typed formula is gone. `LiftReportPayloadDto` (`lift_report_payload_dto.py`) has 13 fields, 9 of them `list[... | dict[str, Any]]` unions and 4 pure `list[dict[str, Any]]`. Everything past `_formula_to_rpc` is untyped. **This door is the census.**

### The `#3220` double-emission seam (the attributed-graph payoff target)

`_emit_euf_fact` is reached from TWO consumers that `_lift_assert:366` merges via `_merge_lifts`:
- **Path A (vendor/bridge-chain):** `literal_call_report.py:732` swears the vendor's stated rhs.
- **Path B (demanded-floor):** `literal_call_report.py:976` (`emit_projected_fact` inside `_construct_callsite_from_factory_term:873`, reached only when `callee_name in functions_by_name`) swears the derived floor.

Both spell the same `#euf#` key. In the truthful case they produce two IDENTICAL golden rows (two warrants implied, one earned); in the lying case they produce two DIFFERING rows whose conjunction is the UNSAT. `BridgeStrategy.emit` (`sugar/call_sugar.py:70-105`) is NOT itself a second emit — it appends `(target_name, floor)` to `ctx.dig_sink` (`:92`) and returns a typed `Complete(CallSiteValue)` (`:97`). The duplication is between the two `_emit_euf_fact` consumers, not in BridgeStrategy.

### The shadow interpreter over raw dicts (the most untyped file)

`floor_contract_agreement.py` (the just-armed agreement gate) is an entire formula interpreter over raw dicts: `_formula_models` (`:85`) hand-matches `formula.get("kind")=="atomic"`/`"and"`; `_normalize_term` (`:107`) hand-matches `term.get("kind")`; `_fold_ctor` (`:130`) hard-codes `{"+","-","*"}` and inlines the sort literal `{"kind":"primitive","name":"Int"}`. It exists ONLY because the floor's typed `Formula` was flattened at the DTO door — a typed carrier retires this whole file.

### Rust is already mostly typed (why it is a mirror, not the center)

`sugar-ir-types` carries serde enums `IrFormula`/`IrTerm`/`Sort` and `ContractDecl{ Rc<Formula>, Rc<Term> }`; `sugar-lift-rust-tests/src/sugar/source_contract.rs` emits typed `ContractDecl`; `sugar-ir-compiler-smt-lib/emitter.rs` matches the enums exhaustively and refuses via typed `CompileError::MalformedIr`. Rust's `Outcome` (`sugar-lift-rust-tests/src/lib.rs:9037`) already types `Incomplete(Effect)` with `Effect::CoverageGap{boundary, reason}` (`:9120`, #3017 item 9). The residual Rust untyped sites are `serde_json::json!` locus/diagnostic scaffolds in `sugar-walk` (`contract.rs:142`, `envelope.rs:322-342`, `lift.rs:3685-3701`). The typed-carrier PRECEDENT to copy is `StoredMember` + closed `MemberKind` (19 variants, `sugar-proof-envelope/src/typed_member.rs`, campaign #3041): a closed node-kind enum + typed carrier + single normalizer, strings only at the serde/display boundary.

### The census (R baseline, distinct ad-hoc emission sites per kit)

| Node class | Python (untyped) | Rust (untyped) | Where |
|---|---|---|---|
| A EqualityFact / `#euf#` contract-row | ~6 | 0 | `literal_call_report.py:774-780,:827,:1252-1300,:1408-1465`; carrier `body_universe_dto.py:15-17` |
| B BridgeObligation / CallEdge | ~2 | 1 | `literal_call_report.py:1580-1596` (hand-built `dict` despite typed `CallEdgeDecl`); Rust `contract.rs:142` |
| C GuardedPost / BodyStepConstraint | ~2 | 0 | `literal_call_report.py:1253-1256,:1310-1324` |
| D RefusalRecord (dig-refusal / agreement-violation / coverage-gap) | ~3 shapes (~10 sites) | 2 | `dig_refusal.py:16`, `floor_contract_agreement.py:12-39`; Rust `smt-lib/emitter.rs:274`, `lift.rs:3685` |
| E SourceAudit / FactoryWalkMemento | ~3 | 0 | `literal_call_report.py:1773-1810`, `lift_report_payload_dto.py:67-76` |
| F UniverseMint / FunctionContract | ~1 | 2 | `literal_call_report.py:1292-1300`; Rust `envelope.rs:322-342` |
| G VendorConjoin / Diagnostic | ~2 | 0 | `lift_report_payload_dto.py:36-37`, `literal_call_report.py:199,:1408-1428` |
| **Total distinct ad-hoc sites** | **~19 (≈27 w/ refusal call-sites)** | **~5** | |

**The R vector this campaign drives:**
- `R(untyped-emission-sites)` per kit — every site that builds a formula/contract-row/refusal/audit/edge as a raw `dict`/`str` instead of a typed ProofIR node constructor. Baseline: Python ~19 (~27 w/ refusal call-sites), Rust ~5.
- `R(formula-fragments-without-provenance)` — every emitted formula fragment that does not carry its `{node-class, construction-site, provenance}` attribution. Baseline: all of them (the DTO stores a bare `dict`).
- `R(proofir-classes-without-verdict-witnesses)` — every node class lacking a solver-anchored `{truthful → SAT, lying-twin → UNSAT}` pair. Baseline: all classes (none exist yet).

## The target vocabulary (node classes, derived from the census)

Each class below is a real emission shape in the graph today. Each gets: a **denotation** (the FOL template it instantiates, over the EXISTING `ir.py` `Term`/`Formula`/`Sort` algebra — never a new DSL), **constructor invariants** (what makes construction well-formed; violation is a construction-time refusal, not a downstream check), and a **verdict-witness pair** (a truthful instantiation that must solve SAT and a lying twin that must solve UNSAT, run through the real solver in the vocabulary harness).

- **`EqualityFact` (Class A) — the spine.** Denotation: `eq(euf_call_term(callee, args), rhs)` under a `#euf#` key. Constructor: `EqualityFact(euf_key, call_term, rhs_term, provenance)` where `provenance: Stated(vendor_locus) | Derived(floor_provenance)`; invariants: `call_term` is a well-sorted `Ctor` head, `rhs_term` sort-agrees with the call's return sort, `euf_key` is derived from `(callee, arg-sig)` not free-typed. Witness pair: truthful `A()->B()->0` with vendor `==0` collapses to ONE node bearing `{Stated, Derived}` → SAT; lying `assert A()==1` stays TWO nodes (`==1` Stated, `==0` Derived) → UNSAT. This node carries the #3220 fix by construction.
- **`FunctionContract` / `UniverseMint` (Classes C, F) — the BodyUniverse carrier.** Denotation: `forall formals. (pre → post)` over the callable's symbol (the typed interface SHARED-LANGUAGE names as the composition node label). Constructor: `FunctionContract(symbol, formals, pre, post, warrants)`; invariants: `out` binding present, `pre`/`post` are `Formula` (not `dict`), `formals` sorts declared. Witness pair: a callable whose `post` its floor models → SAT; a `post` its floor contradicts → UNSAT (this is exactly what `floor_contract_agreement` checks today over raw dicts — the node OWNS it).
- **`RefusalRecord` (Class D) — the Incomplete expression.** Denotation: NO formula (honest absence); a typed record naming the effect. Constructor: `RefusalRecord.from_incomplete(Incomplete)` / `.from_gap(FactoryGap|DigRefusal|CoverageGap)`; invariant: an `Outcome::Incomplete` has EXACTLY ONE vocabulary-legal expression — a `RefusalRecord` — never a silent skip and never a fact. This is where Python's `Incomplete.effect: object` gets a typed `Effect` union mirroring Rust's `Effect::CoverageGap`. Witness pair: a refused dig emits a `RefusalRecord` and NO `#euf#` fact (the vendor's word stands unrefuted → the bundle is still SAT, bridge-only); a bug that tried to emit a fact AND a refusal for one Outcome is a construction-time refusal.
- **`BridgeObligation` / `CallEdge` (Class B).** Denotation: `post(callee)[formals := actuals] → pre(caller)` — the composition edge (SHARED-LANGUAGE's implication). Constructor: reuse the EXISTING typed `CallEdgeDecl`/`BridgeDecl` (`ir.py:642`/`:511`) instead of the hand-built `dict` at `:1580`. Witness pair: a sound `post → pre` edge → SAT; `post ∧ ¬pre` → UNSAT (the refuse arm).
- **`SourceAudit` / `FactoryWalkMemento` (Class E)** and **`VendorConjoin` / `Diagnostic` (Class G)** are provenance/reporting carriers migrated later (S7); their invariant is that every row references a live node-class + construction site (feeds `R(formula-fragments-without-provenance)`).

**No `GenericFact`.** There is no semantic-wildcard node class. A shape not yet expressible refuses loudly (`RefusalRecord` / `FactoryGap`), exactly like the floor base's `to_term` gap (`floor_value.py:11`). A wildcard would be the side door (see Anti-goals).

## Where construction happens — the vocabulary is the codomain of the Outcome algebra

This is the load-bearing S2 design, and it must be gotten right: **the vocabulary is NOT a free-floating layer. It is the natural codomain of the existing reduction algebra** (`Complete`/`Incomplete`, the floors, `desugar`, `project_callsite_with`). Construction happens at the moment a floor meets an assertion/contract position — AFTER `desugar` has composed and reduction has terminated in `Complete(floor)` (or honestly refused via `Incomplete(effect)`).

**The type-flow (each arrow names the type that crosses it today; a `Json`/`str` arrow is a census row):**

| Arrow | Where | Type crossing today | Target |
|---|---|---|---|
| AST → `desugar` | `SugarBody.reduce -> Outcome` | typed `Outcome` | unchanged |
| `desugar` → `Outcome<floor>` | `Complete.value: FloorValue` / `Incomplete.effect: object` | Complete: **typed floor**; Incomplete: **`object`** (soft spot) | Incomplete: typed `Effect` union |
| bridge emit → CallSiteValue | `call_sugar.py:97`, `dig_sink.append` `:92` | typed `CallSiteValue`; sink `tuple[str, FloorValue]` | unchanged |
| floor → projection | `CallsiteProjectionOperation` `operations/callsite_projection_operation.py` | **typed `Formula`** = `eq(Term, Term)` | unchanged (this is the seat) |
| projection → ProofIR node | `_emit_euf_fact` `literal_call_report.py:744` | **`Formula` → `dict` via `_formula_to_rpc:774`** | `Formula` → **`EqualityFact` constructor** (typed) |
| node → attributed graph | `BodyUniverseDto` store | `dict[str, Any]` | typed node w/ provenance |
| graph → FOL/SMT | `_formula_to_rpc` → verifier | RPC/DTO → SMT | serialize AT THE EDGE from the typed node |

**Parse-don't-validate means the algebra's types flow INTO the constructors, not get serialized and re-parsed at the door.** If a constructor takes a raw string/dict where a floor or `Formula` exists, the design is wrong — the floor/`Formula` IS the well-formedness witness. `EqualityFact` consumes the `Formula` that `project_callsite_with` already returns; it never re-parses a dict.

**Single-seat construction (the #3220 root cause, stated as a design rule).** Exactly ONE seat owns construction per assertion: the projection consumer (`_lift_assert`'s merged emit). `BridgeStrategy`/dig paths HAND floors and pointers to that seat (via `dig_sink` and the `CallSiteValue` term); they do NOT emit independently. The vocabulary must not tempt per-statement emission that double-counts what `desugar` composition already folded — a composed block/try/map reduces to ONE exit floor which projects to ONE fact. The `EqualityFact` provenance distinction is what lets the single seat legally carry two warrants for the truthful case without two rows.

**Python↔Rust seam parity.** Both kits share the seam shape: `Complete<floor>` / `Incomplete<effect>`, with `Effect::CoverageGap` the honest "reached a floor, no owning arm yet" record (already typed in Rust at `lib.rs:9120`). The Python `RefusalRecord`/typed-`Effect` work brings Python to parity so the two vocabularies express the same seam in SHARED-LANGUAGE terms.

## Campaign law

1. **Instrument before typing the door.** S1 lands the census auditor, the provenance counter, and the verdict-witness-coverage counter, RED with pinned baselines, before any emission site changes. The auditor names every current `dict`/`str` emission site and its typed-node replacement.
2. **Red-first every slice.** The first artifact is a red instrument or a red compile/gate seam, not a green diff. The return-type flip (S3) landing RED and enumerating N offenders is a valid red-first transcript. So is a verdict-witness bad-twin (a lying twin that must go UNSAT) before its node class exists.
3. **The panic is sacred; never suppress the floor.** `FactoryGap`, `DigRefusal`, `CoverageGap`, and the armed `floor_contract_agreement` gate are honest floors. No slice softens a refusal, turns an `Incomplete` into a silent fact, or drops it silently. An `Outcome::Incomplete` has exactly one vocabulary-legal expression (a `RefusalRecord`).
4. **Semantics lives once, on the vocabulary.** A node class owns its denotation, invariants, and witnesses. No slice re-implements a denotation in a sugar or a consumer. The `floor_contract_agreement` raw-dict interpreter is DELETED, not relocated.
5. **Stated-vs-derived is sacred.** Dedup is by `(key, IDENTICAL formula, distinct provenance)` ONLY, never by key alone. Dropping the differing stated fact in the lying case is UNSOUND and forbidden.
6. **Byte-compat on goldens.** Each migration slice is byte-behavior-preserving on the pinned assertion/golden fixtures, EXCEPT the deliberate golden changes the #3220 collapse requires — those are documented and re-pinned in the same slice (campaign law: a deliberate golden change is stated on the record and re-pinned, never silent).
7. **Climb the ladder.** The return-type frontier belongs to the compiler (Rust) / a pyright gate + a runtime `FactoryGap` seam (Python) — the top rung. The auditor survives only for what types cannot yet see: provenance completeness and the single-seat invariant. Prefer the fix that makes the untyped shape unrepresentable over the fix that detects it.

## Instruments

### Instrument A — emission-site census auditor

A collector/gate (same shape as the second-engine auditor in the floor-projection campaign and the `proof_api_audit` raw-pool axis). It classifies every production site that builds a formula/contract-row/refusal/audit/edge as a raw `dict`/`str` (the census table above), records `R(untyped-emission-sites)` per kit and per class, and prints each offender's typed-node replacement (`EqualityFact`, `FunctionContract`, `RefusalRecord`, `CallEdgeDecl`, …). Exempt: the `ir.py` typed core, serde/JCS/`encode_jcs` boundaries, and cfg(test)/fixture helpers. Red-first: plant one raw-dict emission; the auditor goes red naming file:line + replacement. Pin the baseline (S1); ratchet DOWN.

### Instrument B — provenance-completeness counter

For every emitted formula fragment in a lift, check it carries its `{node-class, construction-site, provenance}` attribution. Report `R(formula-fragments-without-provenance)`. Start as a COUNTER in the payload diagnostics; arm as a gate at close (orphan formulas inexpressible). This is the axis the type system cannot yet fully own (a graph type carrying MANDATORY provenance is the retirement target) — so it stays an auditor after the return-type axis has gone to unrepresentable.

### Instrument C — verdict-witness harness (solver-anchored, once per class)

For every ProofIR node class, run its `{truthful → SAT, lying-twin → UNSAT}` pair through the REAL solver, in the vocabulary's own harness (NOT in sugar tests — sugars never touch the solver). Report `R(proofir-classes-without-verdict-witnesses)`. Red-first: a class registered without a passing witness pair is red. This is the instrument that pins "semantics lives on the vocabulary": if a class's denotation is wrong, its lying twin fails to go UNSAT.

### Instrument D — return-type frontier (the compiler rung; armed in S3)

The abstract emission base's construction method returns ONLY the typed vocabulary (`ProofIRNode`). Rust: rustc's error list is the frontier. Python: a pyright/mypy CI gate pinned to the campaign files (`factory/`, `floor/`, `operations/`, the emission seat) PLUS a runtime `isinstance` check at the single reduce→emit seam that raises `FactoryGap` on a raw `dict`/`str` return (the panic rung backing the type rung, because Python's static typing alone cannot gate it). The offender list IS `R(untyped-emission-sites)` — free, undriftable, unsanctionable.

## Ratchet vector

| Signal | Starts as | Target |
|---|---|---|
| `R(untyped-emission-sites)` — Python | S1 measures (~19; ~27 w/ refusal call-sites). | 0 after the Python deletion slice. |
| `R(untyped-emission-sites)` — Rust | S1 measures (~5; `serde_json::json!` scaffolds). | 0 after the Rust phase (post-irterm-boundary). |
| `R(formula-fragments-without-provenance)` | S1 counter (all fragments — DTO stores bare `dict`). | 0, then armed as a gate (orphans inexpressible). |
| `R(proofir-classes-without-verdict-witnesses)` | S2 measures (all classes). | 0 for the enumerated vocabulary; base node refuses the rest. |
| `R(emission-base-returning-raw-dict-or-str)` | S3 flip lands RED (N offenders = the census). | 0 (clean compile/gate = stable zero by construction). |
| `R(duplicate-emission-rows)` (#3220) | S4 measures (bridge-chain + demanded-floor identical rows). | 0 via provenance collapse; lying-case conjunction preserved. |
| `R(shadow-interpreter-files)` | 1 (`floor_contract_agreement.py` over raw dicts). | 0 (denotation owned by `FunctionContract`). |
| `R(incomplete-effect-untyped)` — Python | 1 (`Incomplete.effect: object`). | 0 (typed `Effect` union, Rust parity). |

## Slices

### Slice 0 — Plan PR

Land this document only. Post the #3220 subsumed-by-campaign comment and the #3150 successor-campaign comment (coordinator).

Exit: merged as "Part 1 of the ProofIR semantic-vocabulary campaign (plan)".

### Slice 1 — Instruments (census auditor + provenance counter + verdict-witness coverage + baselines)

Add Instruments A, B, C; run RED/measuring against main; pin the vectors. Coordinate the census auditor's collector with the existing emission-adjacent auditors.

- Auditor A classifies every raw-`dict`/`str` emission site in `literal_call_report.py`, `body_universe_dto.py`, `lift_report_payload_dto.py`, `dig_refusal.py`, `floor_contract_agreement.py` (Python) and the `serde_json::json!` scaffolds in `sugar-walk` (Rust), each row naming its typed-node replacement.
- Counter B reports `R(formula-fragments-without-provenance)` on the pinned fixtures.
- Counter C enumerates the node classes and reports `R(proofir-classes-without-verdict-witnesses)` (all, pre-spine).
- Bad-twins: plant one raw-dict `EqualityFact` emission (auditor A red; delete before merge); plant a fragment with no provenance (counter B increments).

Exit: three instruments red/measuring; every vector pinned; the census named with per-site replacements.

### Slice 2 — The vocabulary spine (base node + 3 highest-traffic classes + verdict harness)

Add the `ProofIRNode` base and the three highest-traffic classes: `EqualityFact` (Class A, provenance-carrying), `FunctionContract` (Classes C/F, the BodyUniverse carrier), `RefusalRecord` (Class D, the `Incomplete` expression). Each owns its denotation (a template over `ir.py` `Term`/`Formula`/`Sort`), its constructor invariants (well-sortedness, `out` binding, provenance present, exactly-one-expression-per-Outcome), and its verdict-witness pair wired into Instrument C's harness (real solver). Design them as the codomain of `Outcome<floor>` per the type-flow section — constructors consume typed floors / `Formula` / typed refusals, NEVER raw dicts. Do NOT yet re-point the DTO door; this slice adds the classes and their solver-anchored witnesses in isolation.

- Red-first: `Instrument C` red for each class until its witness pair passes; a lying twin that fails to go UNSAT is red.
- Bad-twins: (a) `EqualityFact` truthful twin collapses to one two-warrant node → SAT; (b) `EqualityFact` lying twin stays two nodes → UNSAT; (c) `RefusalRecord.from_incomplete` on an `Incomplete` that ALSO carries a fact refuses at construction.
- Pinned tests: a new `test_proofir_vocabulary_witnesses.py` (the harness); existing suites stay green (door not yet re-pointed).

Exit: three node classes own their denotation + invariants + solver-anchored witnesses; `R(proofir-classes-without-verdict-witnesses)` measured and zero for the spine set.

### Slice 3 — Return-type flip (the compiler/gate frontier)

Flip the abstract emission base's construction method to return ONLY `ProofIRNode`. Land RED. Python: base return annotation + pyright/mypy gate pinned to the campaign files, PLUS a runtime `isinstance` check at the single reduce→emit seam raising `FactoryGap` on a raw `dict`/`str`. Rust: literal return-type change (stageable per-crate). The offender list IS `R(untyped-emission-sites)`.

- Red-first: the flip lands RED — the gate/compiler enumerates every site still returning a raw `dict`/`str`.
- Bad-twin: a site returning a raw dict must fail the gate / raise `FactoryGap`; a site returning a `ProofIRNode` passes.
- Staging tradeoff (documented; hard flip preferred): if a hard flip breaks the build unacceptably long, the fallback is a deprecated union return `ProofIRNode | RawLegacy` + a shrinking warning-as-error allowlist. Recommend the hard flip; name the union only as the escape hatch.

Exit: the frontier is armed; `R(emission-base-returning-raw-dict-or-str)` pinned at N (the census); each subsequent slice shrinks it.

### Slice 4 — Migrate `EqualityFact` + subsume #3220 (provenance collapse)

Re-point `_emit_euf_fact` (`literal_call_report.py:744`) to construct an `EqualityFact` (carrying `Stated`/`Derived` provenance) instead of the raw-dict `inv`. Route both consumers (Path A `:732`, Path B `:976`) through the single seat handing the node its provenance. Collapse by `(key, identical formula, distinct provenance)` → one node, two warrants (the truthful case); leave differing-formula rows as two nodes (the lying case → UNSAT). Document + re-pin the golden byte changes the collapse causes.

- Bad-twins: (a) `A()->B()->0` with vendor `==0` → one two-warrant node → SAT, golden shows ONE row; (b) `assert A()==1` (lie) → two nodes → UNSAT (the discrimination the whole substrate exists for); (c) a refused dig → `RefusalRecord`, no fact, bundle still SAT.
- Pinned tests: `test_callsite_emission_golden.py` (re-pinned), `test_transitive_construction.py`, `test_dig_refusal_ledger.py`.

Exit: `EqualityFact` is the only `#euf#` emitter; `R(duplicate-emission-rows)=0`; #3220 subsumed; the untyped-site count drops by Class A.

### Slice 5 — Migrate `FunctionContract` / BodyUniverse; retire the shadow interpreter

Make `BodyUniverseDto.{pre,post,inv}` carry typed `Formula` (via `FunctionContract`) instead of `dict`. DELETE `floor_contract_agreement.py`'s raw-dict `_formula_models`/`_normalize_term`/`_fold_ctor` interpreter — the `FunctionContract` node OWNS the floor⊨post denotation. Keep the agreement GATE armed (it now checks the typed node, not a dict).

- Bad-twins: (a) a callable whose floor models its post → SAT (gate green); (b) a floor contradicting its post → UNSAT (gate red); (c) a malformed `post` (no `out` binding) refuses at construction, not at the gate.
- Pinned tests: the `floor_contract_agreement` gate suite (now typed); function-universe golden fixtures.

Exit: `R(shadow-interpreter-files)=0`; BodyUniverse carries typed formulas; untyped-site count drops by Classes C/F.

### Slice 6 — Migrate `RefusalRecord` + type `Incomplete.effect`

Give Python `Incomplete.effect` a typed `Effect` union mirroring Rust's `Effect::CoverageGap`. Route `dig_refusal.py`, the agreement-violation records, and every `Incomplete` through `RefusalRecord` (exactly one vocabulary-legal expression per Outcome). No `Incomplete` may become a fact or a silent skip.

- Bad-twins: (a) an effectful callee → `RefusalRecord`, bridge-only, SAT; (b) an `Incomplete` that tried to emit both a fact and a refusal refuses at construction; (c) a `CoverageGap` (floor reached, no owning arm) records loudly, never silently drops.
- Pinned tests: `test_dig_refusal_ledger.py` (same-or-more-precise refusals); a new Incomplete-expression test.

Exit: `R(incomplete-effect-untyped)=0`; every `Incomplete` has one typed expression; untyped-site count drops by Class D.

### Slice 7 — Migrate Bridge/CallEdge, SourceAudit/walk-memento, VendorConjoin/diagnostics

Route Class B through the existing typed `CallEdgeDecl`/`BridgeDecl` (delete the hand-built `dict` at `literal_call_report.py:1580`); route Classes E and G through typed carriers referencing a live node-class + construction site (feeding provenance completeness).

- Bad-twins: (a) a sound `post→pre` edge → SAT; (b) `post ∧ ¬pre` → UNSAT; (c) an audit row with no owning node refuses.
- Pinned tests: call-edge golden fixtures; report-shape suites.

Exit: untyped-site count drops by Classes B/E/G; `R(formula-fragments-without-provenance)` approaches zero.

### Slice 8 — Delete the raw door; arm the provenance + attribution gates; close (Python)

Delete the `_formula_to_rpc → dict[str, Any]` DTO store path (BodyUniverseDto and LiftReportPayloadDto carry typed nodes; serialization happens AT THE EDGE from the typed node). Instrument A pins `R(untyped-emission-sites)=0` (Python); flip Instrument B (provenance) and the attribution check from counters to GATES (orphan formulas inexpressible).

- Red-first: the auditor gates flip to expect zero; deletion turns them green. Structural grep in the PR body: `rg -n '_formula_to_rpc|dict\[str, Any\]' implementations/python/sugar-lift-py-tests/src` → no production emission hits.
- Bad-twins: re-run the Slice 4 discrimination trio against the deleted-door build; plant an orphan fragment → provenance gate red; remove → green.
- Pinned tests: full `sugar-lift-py-tests` suite green.

Exit: no raw emission door in Python; auditor + structural grep agree on zero; provenance/attribution are armed gates.

### Slice 9+ — Rust mirror phase (own slices, sequenced AFTER irterm-boundary #3198)

Mirror the vocabulary onto the ~5 residual Rust `serde_json::json!` scaffolds (`contract.rs:142`, `envelope.rs:322-342`, `lift.rs:3685-3701`), reusing the `StoredMember`/`MemberKind` typed-carrier precedent. Rust is mostly typed already, so this is small — but it MUST land after the irterm-boundary campaign has collapsed `IrTerm`→`Rc<Term>` (see Sequencing): running an emission-vocabulary byte change while the boundary refactor is holding `R(byte-drift)=0` would make byte-drift ambiguous and destroy the boundary campaign's acceptance instrument.

Exit: `R(untyped-emission-sites)` Rust = 0; both kits express the same seam in SHARED-LANGUAGE terms.

## Sequencing with sibling campaigns

- **irterm-boundary #3191-#3198 (Rust term collapse) — MUST land before the Rust phase (S9+).** irterm-boundary collapses the term-REPRESENTATION/dispatch layer (`IrTerm` vs `Rc<Term>`, one dispatch world) and its entire safety mechanism is `R(byte-drift)=0` on every slice. This campaign types the EMISSION VOCABULARY that sits ON TOP of that representation and DELIBERATELY changes emitted bytes (the #3220 collapse, typed re-pins). The two are orthogonal layers but must not overlap in time: land irterm-boundary first so `Rc<Term>` + closed visitors is the single world and the byte baseline is clean, then re-pin the wire vocabulary against that stable substrate. The Python phase (S1-S8) has NO overlap with irterm-boundary (different kit) and proceeds in parallel.
- **The sugar shape/witness trait campaign (`mine()`/`near_miss()`) — AFTER S2.** A sugar's structural testimony needs the typed vocabulary to testify AGAINST ("for my shape, I constructed these ProofIR objects"). It cannot be planned until the vocabulary exists. Plan it after S2 lands.
- **py-kit recognizer tail — independent, no conflict.** Recognizer work adds shapes to the factory; it feeds the vocabulary but does not collide with it.

## Anti-goals

- **No bespoke FOL DSL.** Denotations are templates over the EXISTING `ir.py` `Term`/`Formula`/`Sort` algebra (SHARED-LANGUAGE: ProofIR is always first-order logic; no bespoke contract language). A node class instantiates a template; it does not invent a formula syntax.
- **No `GenericFact` / semantic wildcard node.** A shape not yet expressible refuses loudly (`RefusalRecord`/`FactoryGap`). A wildcard node would be the side door the factory-or-side-door law forbids, one level down.
- **No weakening of any armed gate.** The `floor_contract_agreement` gate, the `DigRefusal` ledger, and every panic stay armed and get MORE precise. Retiring the shadow INTERPRETER (S5) is not weakening the GATE — the gate now judges a typed node.
- **No solver in sugar tests.** Verdict witnesses run in the vocabulary's own harness (Instrument C). Sugars never touch the solver; their testimony is purely structural.
- **No dedup by key alone.** Stated-vs-derived is sacred; collapse only `(key, identical formula, distinct provenance)`. Dropping the differing stated fact in the lying case is UNSOUND.
- **No relocating the shadow interpreter.** Deleting `floor_contract_agreement.py`'s raw-dict fold means the denotation lives on `FunctionContract`, not in a renamed helper.
- **No Rust emission byte change during irterm-boundary.** The Rust phase waits for #3198.

## Campaign closure

1. Every ProofIR emission is a constructor call on a typed node class; `R(untyped-emission-sites)=0` in both kits; structural grep agrees.
2. Each node class owns its denotation, constructor invariants, and a solver-anchored `{SAT, UNSAT}` verdict-witness pair; `R(proofir-classes-without-verdict-witnesses)=0`; sugars touch no solver.
3. The proof graph is fully attributed; `R(formula-fragments-without-provenance)=0` as an armed gate; orphan formulas are inexpressible.
4. `EqualityFact` carries `Stated`/`Derived` provenance; #3220 is subsumed (`R(duplicate-emission-rows)=0`) and the stated-vs-derived UNSAT is preserved by construction.
5. `floor_contract_agreement.py`'s raw-dict interpreter is deleted; the agreement gate judges the typed `FunctionContract`; `R(shadow-interpreter-files)=0`.
6. Python `Incomplete.effect` is a typed `Effect` union at Rust parity; every `Incomplete` has exactly one `RefusalRecord` expression.
7. The full `sugar-lift-py-tests` suite passes; the pinned goldens are re-pinned where the #3220 collapse deliberately changed them, documented on the record; the vendor-lie fixture still goes UNSAT.
