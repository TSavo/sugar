# Goal: stdlib `unclassified` → 0

> **STATUS 2026-06-13 overnight (commits 3cbf69936..1c884119a, all pushed, all
> verified falsePass=0).** Baseline `--rustc-cfg`: discharged 5088 / refused 201 /
> unclassified 1082 / inactive 58. Sound progress landed: honest accounting
> (Inactive + temporally-unstable-terminal), and 2 of the 3 body-level capabilities
> the unclassified set bottoms out in — **statement-position helper inlining** and
> **pure let-substitution** — both tested. The headline is unchanged because the
> ~1071 remaining is gated on capability #1, **higher-order closure/generic-body
> inlining** (the 517 flt2dec helpers + ~150 term-position closures): a mis-lift
> there is a MASKED-CONTRADICTION falsePass the consistency sweep cannot catch, so
> it is the one piece I will NOT forge unsupervised. Reaching literal 0 needs that
> capability assembled with the other two — a supervised step. Everything below is
> the diagnosis and the plan; the comparison-op revert is the cautionary example of
> why shared-path lifter changes need a human in the loop.



## The target (closure invariant)

For the stdlib (rust 1.96.0 coretests) corpus, drive **`unclassified = 0`**. Not
`refused = 0` (terminal refusals are earned and stay), not `discharged = 100%`
(some asserts genuinely refuse). The endgame is the **totally-classified ledger**:

```
total  =  discharged  ⊎  refused(terminal)  ⊎  inactive
          unclassified = 0          (no load-bearing AST node un-judged)
          unaccounted  = 0          (no silent drop; tighten the current -51)
```

A CID over that ledger is the closure artifact: every door labelled, no junk
drawer. Until `unclassified = 0`, the ledger CID certifies a completeness it does
not have.

## Progress log (2026-06-13 overnight, --rustc-cfg baseline)

Measured with `coretests_sweep --rustc-cfg` (the canonical config; without it 178
cfg-gated asserts read as ambiguous — a measurement artifact, now fixed).

- **Honest accounting** (commit 3cbf69936): `Disposition::Inactive` splits out
  cfg-disabled asserts (58 — not this target's universe, not work); `temporally
  unstable` joins the terminal whitelist (a source property). discharged 5088,
  refused 201, unclassified 1161→1082, inactive 58.
- **R7 statement-position helper inlining** (commit 8ace70802): bare `check(2);`
  calls to assert-bodied helpers inline per-callsite (β-reduction). Sound + tested.
  Fires for simple helper bodies; drained 0 on stdlib because the 517 here are the
  **complex flt2dec helpers** (`F: FnMut` closure params, nested fns) it correctly
  declines.
- **Comparison-ops in term position** — ATTEMPTED, REVERTED. Adding `<`/`<=`/`>`/
  `>=` to `term_binop_name` discharged +11 (`a[0] < b[0]`) but diverted
  `!(value() < 3)` off the comparison-ATOM path, breaking euf-coalescing of a
  negated comparison with its positive sibling (a guard test). Parked with an
  in-code NOTE; needs a fix that routes top-level/negated comparisons to atoms
  before the term ctor.

**UNIFYING FINDING — the 9 surface rungs collapse to ~3 body-level capabilities.**
The loop lifter (`try_lift_for_loop_forall`) already unrolls literal arrays /
quantifies ranges and substitutes the loop var; it refuses (→ bin-1) only when the
BODY hits `body_skipped` — i.e. the body contains a non-liftable term. Likewise the
helper-inline refuses when the body won't reduce, and the branch/let/nested buckets
are the same. So bin-1 loops (60), complex helpers (517), branch (45), nested (38)
are NOT independent rungs — they are **downstream consumers** that drain
automatically once the body-level gaps close. The whole ~1071 bottoms out in THREE
body-level lifting capabilities:
  1. **Higher-order inlining** (closures `|x| ..` as adapter args / helper params,
     generic+closure helper bodies) — the dominant mass (≈670), the hard core.
  2. **Term vocabulary** (non-closure `unsupported term`/operator — the genuinely
     missing lowerings, e.g. term-position comparisons done right).
  3. **let / nested-expr handling** in a reduced body (`let x = e;` substitution,
     asserts nested in expression statements).
Close those three at the BODY level and the surface rungs follow. All three are
shared-path, regression-prone (cf. the comparison-op revert), and a mis-lift here
is a MASKED-CONTRADICTION falsePass the consistency sweep does NOT catch (it catches
false-unsat, not false-discharge). So they must be done SUPERVISED, one capability
at a time, gated on the full guard-test suite — not forged unsupervised.

**Empirical finding — the remaining ~1071 is mostly HIGHER-ORDER, not micro-lowerings.**
The two biggest buckets (517 complex helpers + ~150 closures-in-term-position) are
the SAME core: lifting requires inlining closures / generic+closure helper bodies
(higher-order β-reduction, possibly iterator-comprehension lifting). That is real,
regression-prone work that must be done SUPERVISED with the consistency-sweep
falsePass net — not forged overnight. A chunk of the flt2dec 517 may further prove
**terminal (bin-2)** once inlinable, because their asserts are about *runtime
formatter output*, not source literals — but we cannot claim that reason honestly
until we can inline far enough to see it, so they correctly stay `unclassified`
(not refused) today. The moderate buckets (bin-1 loop bodies 60, let-init 32,
nested-expr 38, branch 45) are tractable but each risks the same kind of
keying/coalescing side-effect the comparison-op attempt hit; do them one at a time,
each gated on falsePass=0 + the full guard-test suite.

## Where we are (sweep, commit ef1bb4d7c)

```
discharged   4990   78.2%
refused       171    2.7%   (terminal: bin-2 runtime 103, ambiguous-temporal 49, bignum 19)
unclassified 1267   19.9%   <-- this document drains this to 0
unaccounted   -51           (no silent drops; inlining over-count, to be tightened to 0)
```

Each rung is a transformation φ (the homomorphism catalog) that moves a bucket OUT
of `unclassified` into `{discharged | refused(terminal) | inactive}` by its pinning
gate. Draining ≠ all-discharge: a rung splits its bucket — pinned inputs discharge,
genuinely runtime/effectful/dynamic residue becomes a *terminal* refusal.

## The rungs, by leverage (count drained, cumulative)

| # | drains | cum | rung | φ | gate → outcome |
|---|--------|-----|------|---|----------------|
| 1 | **521** | 41% | **R7 call-disappearance → queued dig** | `z=h(x); g(z)` keep `z=h(x), result=g(z)`, **queue h,g**; AST walk done when queue empty | helper body source-resolvable → discharge; dynamic-receiver dispatch / known effect → terminal refuse. (These are the `to_*_str_test` / `check` / `next` helpers "reachable only via call-site inlining" — pure TODO today.) |
| 2 | **258** | 62% | **TERM vocab** | teach the missing term/operator a lowering (incl. term-position macro results) | expressible op → discharge; genuinely non-FOL surface → terminal refuse. Per-operator grind, no single switch. |
| 3 | **178** | 76% | **CFG pin (static-env)** | supply the target triple; resolve `cfg!`/target-gated asserts | a missing INPUT, not a lifter feature — cheapest bang. Pinned cfg → discharge; truly target-divergent → per-target verdict. |
| 4 | **64** | 81% | **R4f loop finite-domain body** | `for x in <literal domain>` → `∀x.(guard ⇒ body)` (the forall lifter already exists; body not yet point-wise) | body lifts → discharge; opaque element data → terminal (bin-2). |
| 5 | **45** | 82% | **R4 branch partitioning** | `if g {A} else {B}` → `g ⇒ out=A ∧ ¬g ⇒ out=B`; with pinned `self.mode` the branch collapses at callsite | guard pinned → discharge; opaque-runtime guard → terminal refuse. |
| 6 | **39** | 86% | **R8 macro type/effect split** | classify `macro expanded to no liftable`: type-level → inactive; effectful → terminal | removes a mixed bucket; no value asserts lost. |
| 7 | **38** | 88% | **R1 nested-expr walk** | lift asserts nested in an expression statement (fluent pinning into the enclosing term) | sub-expression pinned → discharge. |
| 8 | **32** | 91% | **R5 let-init projection** | `let x = <expr>; ..x..` → bind/project `x` to its pinned term | pinned init → discharge; opaque/mutated → refuse. |
| 9 | **31** | 93% | **MAC teach** | lower the remaining assertion macros (`assert_almost_eq!`, `assert_chunks!`, ...) | one accounting unit per source macro. |
| — | **111** | 100% | **tail** | SRC resolve helper source (20, or prove terminal-external) · WALK totality-gap (11) · FLT float refine (9, several already ok) · R5p closure-predicate (8) · CON const-block (6) · PAT pattern (5) · R2 alias/SSA (4) | each small, mostly an existing rung's edge case. |

**Three rungs (R7 + TERM + CFG) = 76% of all remaining work.** R7 alone is 41% and
is the most mechanical — it's the queued-dig you already named.

## Order (leverage × tractability)

1. **CFG (178)** first — cheapest, it's an input not a feature; clears 14% by
   supplying a target triple and resolving cfg-gated asserts.
2. **R7 call-queueing (521)** — the dominant lever; build the dig worklist
   (resolve helper source → inline at callsite → lift body → recurse until queue
   empty), with dynamic dispatch as the terminal-refuse leaf.
3. **TERM (235)** — grind the operator vocabulary; each unsupported term either
   gets a lowering (discharge) or a "not expressible in FOL" terminal refusal.
4. **R4 family (110)** — branch partitioning + finite-domain loop bodies (one
   mechanism: `guard ⇒ out`, finite/non-quantified case of the forall lifter).
5. **Tail (193)** — R8 split, R1 nested, R5 let-init, MAC, then the long edge cases.

## Done means

After every rung, re-run `coretests_sweep`. The milestone is met when it prints
`unclassified 0` with `unaccounted 0`, and `refused` is a *short, debunk-proof*
list of source-property reasons (runtime data, dynamic dispatch, values outside the
sort). At that point the ledger CID is a real closure artifact: 64 bytes over a
house with every door labelled.
