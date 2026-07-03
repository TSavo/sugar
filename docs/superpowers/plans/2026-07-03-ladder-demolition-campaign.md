# Ladder Demolition Campaign — Phase 4: route lift.rs walkers through the catalog

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. The
> coordinator dispatches slices ONE AT A TIME from current main. Instruments come
> before drains, every slice is red-first, and **byte-compatibility of emitted
> proof/verifier output is the acceptance bar on every demolition slice.** Read
> `AGENTS.md` (IDD manifesto, enforcement ladder, coordination density, the capstone
> law, construction closure, the error-message corollary) and this plan's decision
> of record before your first line. Every claim below was verified against live main
> (`0c6b0fc83`) at plan-writing time; re-verify against your base.

**Campaign umbrella:** #3027 ([rust-kit][campaign] Phase 4: match-ladder demolition).
**Prerequisite (MADE):** the IrTerm-vs-`Rc<Term>` seam — Option A, realized and gated
by the irterm-boundary campaign (PR #3392: single boundary, `Rc<Term>` + closed
visitors, IrTerm as edge serialization; `R(structural-irterm-reasoning-sites)=0`
armed). Ladders route THROUGH `build_term`/`build_expr_role` into the algebra.
**Consumes:** the Phase 2 effect algebra (CLOSED), the temporal floors (S1–S6
landed; S7 close in flight), the witness enrollment gates (CLOSED, both kits).
**Downstream:** #3043 (rust-kit closure capstone) counts this campaign's vectors.

## Goal

Demolish `sugar-walk/src/lift.rs`'s hand-rolled match-ladder walkers (6,557 lines
live; the issue's 5,133 grew) plus the satellite ladders (`emit.rs` 3,268,
`walk.rs` 1,025, `loops_and_exceptions.rs` 641, `sugar-lift/src/call_edges.rs`
595) by routing every construct family through the catalog into the algebra —
factory-recognizes, desugar-unrolls, one boundary — and deleting the ladder arms.
Exit: the ladder census at zero-or-declared per family, the silent-drop floor
green throughout, bytes conserved on every slice.

## Decision of record (T Savo, 2026-07-03)

**BACKSTOP-FIRST** — T's verbatim ruling on the demolition order: **"Obviously b."**
The silent drops are the actual crime; the ladders are just where they live. Flip
the fall-through to loud first; demolish at leisure once every gap is visible.

**Reality reconciliation (measured at plan time, per the measure-pins-per-branch-state
law):** the backstop-first substance is ALREADY REALIZED. The #3021 silent-drop
frontier (R=401 at instrument landing: ok=47, unwrap_or=118, unwrap_or_default=53,
wildcard_empty_block=49, wildcard_none=134) was drained to **stable zero** by a
prior drain arc — #3022/#3023/#3024 (all CLOSED) plus a dozen `Drain … frontier`
commits (`0b86da60b`…`65b12d965`) and the excision (`565fe0654`) — with the
genuinely-fine residue sanctioned **per-site, in code, with reasons**
(`// sugar-audit: not-mine(...)` comments; e.g. `emit.rs:2512` scalar-sort
fall-through). The instrument (`sugar-walk/tests/silent_drop_frontier.rs`) scans
sugar-walk/sugar-lift/sugar-lift-contracts src live, `EXPECTED_FRONTIER` is empty,
and `silent_drop_frontier_stable_zero_target` **passes**. The classifier ladders
now refuse loudly (e.g. `lift.rs:2191` `panic!("…refused unknown syn::Expr
variant")`).

**Therefore the ruling is honored as:** S1 arms the realized backstop as this
campaign's FLOOR (stable-zero on every slice, forever) and audits the in-code
sanctions per tonight's exemption law — then builds the instrument for what
actually remains: the **ladder census** (hand-construction sites that route around
the catalog — the second-representation risk that survives even with every drop
loud). S2+ demolish by family. Any slice that would re-introduce a silent drop
reds the floor immediately — the backstop-first guarantee, standing.

## Instruments (S1 — before any demolition)

- **Floor (armed, inherited):** `silent_drop_frontier_stable_zero_target` becomes a
  hard per-slice floor. R(silent-drops)=0 is the campaign's ground; a demolition
  slice that regresses it is rejected regardless of its other receipts.
- **Sanction audit:** enumerate every `// sugar-audit:` per-site sanction in the
  scanned roots; each keeps a reason that survives review or converts to loud
  refusal. Per tonight's law (the blinded-auditor lesson): an instrument's
  exemptions are part of its jurisdiction — the sanctions become an enumerated,
  test-pinned list (typed rows, not scattered comments the census can't see).
- **Instrument A — the ladder census:** `R(ladder-sites-outside-catalog)`, per
  family: every function in the walker files that constructs `IrTerm`/`IrFormula`
  or classifies constructs WITHOUT routing through the catalog
  (`build_term`/`build_expr_role`) or the algebra boundary. Recomputed from live
  source (the dispatch-matrix/lifter-census pattern — walked, never authored),
  each row carrying owner + target slice + the replacement route. Baseline pinned;
  planted offender red through the real walk.
- **Instrument B (inherited):** the byte harnesses (verify/prove SHAs + planted
  drift) and `assertion_lift_frontier`'s owned 35-row disposition table — the
  demolition drains rows out of `floor-gap:*` buckets it owns there (see the
  #3417 bucket map: iterator/literal/chunk-window/closure-adaptor classes).

## The ladder inventory (live, plan-time)

| Family | Where (live line anchors) | Shape |
|---|---|---|
| tail-expr / ite | `lift.rs` 557–935 (`lift_tail_expr_to_result_term`, `lift_tail_if_to_ite_term`, `cf_ite_via_symbolic_value_boundary`, `lift_match_to_ite_term`, `block_tail_expr`, `wrap_leading_lets`, `formula_to_term` bridges) | tail-position lowering ladders |
| predicates | `lift.rs` (`lift_predicate_inner` + operand bridges) | condition/comparison normalization ladder |
| guard / assertion facts | `lift.rs` 1049–1330 (`collect_assertion_guard_facts`, `tracked_direct_guard_fact`, `tracked_len_eq_one_fact`, `len_*` residue — the irterm S8 demolition took the four worst helpers; this is the remainder) | guard-fact extraction ladders |
| value-kind + macros | `lift.rs` 1550–1810 (`ValueKind` ladders, `lift_macro_to_opaque_term`, json-macro parsing) | classification + macro lowering |
| WP / contract + seeds | `lift.rs` 218–477, 1011–1049 (`lift_function_pre/postcondition*`, `explicit_return_kind`, `seed_*`, `collect_local_value_fact`) | contract-surface lifting |
| panic / loop effects | `lift.rs` 1867–2451 (`collect_guarded_panic_effects_in_expr` etc.) + `loops_and_exceptions.rs` (641 lines) | effect collection ladders (Phase 2 routers are the route) |
| patterns / types + call edges | `lift.rs` 2572–2790 (`Pat`/`Type` ladders) + `sugar-lift/src/call_edges.rs` (595) — note irterm S7 already routed `walk.rs` pattern bindings | structural projection ladders |

## Slices

### S1 — Instruments: the floor, the sanction audit, the census. RED/measuring
As above. No production routing. Red-first: the census red at its live baseline;
a planted un-routed constructor site red through the real walk; the sanction list
pinned with reasons. Exit: floor armed, sanctions enumerated-typed, census
baselined per family with owners.

### S2 — Tail-expr / ite family
Route tail-position lowering through the catalog (the temporal floors own
iterator tails already — consume, don't duplicate; the `cf_head` vocabulary is
owned by the term-boundary raiser per irterm S8). Delete the ladder arms as rows
route. Red-first byte receipts on tail-expr fixtures; bad-twins: an if-tail and a
match-tail emit byte-identically; an unroutable tail REFUSES loudly (floor green).
Exit: family census rows 0-or-declared; bytes 0.

### S3 — Predicate family
`lift_predicate_inner` routes through the catalog's predicate claims (the
PredicateValue floor from #3017 item 8 / irterm S5). Same bar.

### S4 — Guard / assertion-fact residue
The remaining guard-fact extraction routes through the algebra's guard operations
(ControlFlowGuardOperation reachable per irterm close). Same bar.

### S5 — Value-kind + macro family
Classification ladders become catalog recognizers; macro lowering routes
(`matches!`/`vec!` precedent: PR #3430 landed macro-shape facts through the
factory — extend, don't fork). Same bar.

### S6 — WP / contract + seeds family
Contract-surface lifting routes through the typed vocabulary (FunctionContract/
PostCondition per CL S6; the sugar-lift-contracts native-annotation surface is
the sanctioned neighbor — no drift into it). Same bar.

### S7 — Panic/loop effects + patterns/types + call edges
Effect collection routes through Phase 2's routers (they own raise-likes; the
temporal floors own iteration); pattern/type ladders through the catalog claims
(irterm S7's walk.rs precedent); call_edges through the callsite claims. Same bar.

### S8 — Close
Census at zero-or-declared per family with reasons; the flip's refusal vocabulary
retired to unrepresentable where the catalog's totality permits (per the ladder:
a construct family the catalog totally owns cannot reach a lift.rs arm that no
longer exists); lift.rs line count reported (vanity metric, not a gate); the
sanction list re-audited; #3043's conjunction updated; stable-zero declaration.

## Ratchet table

| Vector | Baseline (S1 pins live) | Target |
|---|---|---|
| R(silent-drops) — THE FLOOR | 0 (realized backstop) | 0 every slice, forever |
| R(ladder-sites-outside-catalog), per family | S1 measures | 0-or-declared per family |
| R(sugar-audit-sanctions) | S1 enumerates | typed rows, each reasoned; shrinking |
| assertion_lift `floor-gap:*` owned buckets | 35 rows (per #3417's map) | this campaign's buckets drain |
| R(byte-drift) | 0 | 0 every slice |

## Sequencing

- Independent of the remaining #3415 family drains (different seats).
- Consumes the temporal floors where families overlap iterator territory — the
  #3417 bucket map names the overlap rows (iterator/literal/chunk-window/
  closure-adaptor → temporal); a ladder slice that reaches an iterator tail
  routes through the LANDED floors, never re-implements.
- S2–S7 are pairwise independent after S1 (different function neighborhoods) but
  land ONE AT A TIME (shared file: lift.rs — textual conflicts guaranteed if
  parallel).

## Anti-goals

- **No refusal-deletion to green a row** (the #3021 crime reborn — a census row
  goes green by ROUTING, never by deleting the loud arm that replaced a silent one).
- **No new match ladders** (a demolition slice that adds a ladder arm anywhere red).
- **No per-family IrTerm adapters** (Option B stays dead; the boundary is the route).
- **No weakening the backstop** (the panic at `lift.rs:2191`-class refusals and
  the stable-zero floor are the campaign's ground).
- **No scattered sanctions** (new exemptions enter the typed sanction list with
  reasons, never as loose comments).
- **No walk_rpc/libsugar seam unification** (out of scope per the umbrella; docs
  only where touched).

## Campaign closure

CLOSED when: the ladder census reads zero-or-declared per family; the silent-drop
floor held green through every slice; the owned assertion_lift buckets this
campaign claims are drained; bytes conserved throughout; the sanction list typed
and shrinking; #3043's rust-spine conjunction updated with this campaign's vectors.
At that point lift.rs is a thin dispatcher into the catalog and the algebra — the
factory recognizes, the desugar unrolls, and the hand-rolled second walker of
Rust's grammar no longer exists.
