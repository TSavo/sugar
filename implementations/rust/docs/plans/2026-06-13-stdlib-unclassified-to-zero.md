# Goal: stdlib `unclassified` → 0

> **STATUS 2026-06-14 (commits 3cbf69936..04bcf3da9, all pushed, all verified
> falsePass=0).** Capability work LANDED, driving unclassified **1082 → 950** (−132,
> discharged 5088→5220): (#1) **monotonic statement-helper inlining** — β-reduce +
> recurse the unchanged collector, committed ONLY if the body adds zero unclassified
> (so inlining can only drain, never inflate — the earlier naive version inflated and
> was reverted); (#2) **closures as opaque EUF symbols** keyed by text + version-aware
> captures (drained 124; "unsupported term" 192→78); (#3) **`&mut <closure>/<literal>`
> as opaque `ref_mut`** (guard-preserving — `&mut <variable>` still residual). All
> three sound by construction (conservative EUF / faithful β-reduction / versioned),
> each with a discrimination test; verifier falsePass 0 throughout (undec 24→82 is the
> honest bignum tier the lifts exposed, not a false claim). Remaining 950 is dominated
> by the **516 "reachable only via inlining"**, and a diagnostic pinned the blocker:
> it is **ARCHITECTURAL, not a per-assert gap.** Those helpers (flt2dec
> `to_exact_fixed_str_test` etc.) are DEFINED in `num/flt2dec/mod.rs` but CALLED
> cross-file from `strategy/*.rs`. The lifter processes each file independently with a
> **per-file function registry** (`ReductionCtx.functions` is built from the current
> file's items; only MACROS have a cross-file `imported` registry). So at the
> definition site there is no in-file caller to inline against (Pass 2 refuses), and
> at the caller's site `reducer.function` can't see the cross-file helper's source.
> My within-file inline works (it drained the in-file helpers); the 516 need a
> **whole-program / cross-file function registry** (the analogue of the macro
> `imported` registry) threaded into `lift_file`, plus the cross-file
> inlining-inflation accounting. That is the supervised architectural step for this
> bucket — distinct from the per-assert opaque capabilities, which are done.
> Prior baseline line, for reference: discharged 5088 / refused 201 / unclassified
> 1082 / inactive 58. Sound progress landed: honest accounting
> (Inactive + temporally-unstable-terminal), and 2 of the 3 body-level capabilities
> the unclassified set bottoms out in — **statement-position helper inlining** and
> **pure let-substitution** — both tested. The headline is unchanged because the
> ~1071 remaining is gated on capability #1, **higher-order closure/generic-body
> inlining** (the 517 flt2dec helpers + ~150 term-position closures): a mis-lift
> there is a MASKED-CONTRADICTION falsePass the consistency sweep cannot catch. I
> BUILT #1 soundly anyway (β-reduction + collector-recurse, with a masked-contradiction
> guard test that PASSED — it does not forge) and MEASURED it: inlining ALONE moved
> unclassified 1082→**1094 (worse)** + doubled inflation, because each inlined body
> hits the NEXT gap (closure-adaptor→bin-1, `&mut`-closure) per callsite. Reverted
> (saved: `git stash` + `/tmp/capability1-inline-headstart.patch`). **Measured
> conclusion: #1 is necessary-not-sufficient — it must land WITH closure-adaptor
> lifting + `&mut`-as-opaque as ONE coordinated change**, gated on unclassified
> actually DROPPING. That is the supervised step. Below: the diagnosis, the plan, and
> the measured dead-ends (comparison-op + inline-alone) that bound it.



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

**MEASURED RESULT — capability #1 (inlining) ALONE is net-negative; it must land
WITH closure-adaptor lifting.** I built the sound, contained version (`substitute_stmts`
β-reduction + recurse the unchanged collector on the substituted body; masked-
contradiction guard test passed — inlining does NOT mask contradictions) and *measured*
it on stdlib rather than assume. Result: discharged 5088→5093 (+5), refused 201→235
(+34), **unclassified 1082→1094 (+12, WORSE)**, inlining-inflation 52→103 (doubled).
The inlined bodies hit downstream gaps PER CALLSITE — `check`'s `.all(closure)` over a
now-literal slice → bin-1 (still unclassified, ×callsites); flt2dec's `to_string(&mut f_,
…)` → `&mut`-closure residual. So inlining replaces each "reachable only via inlining"
refusal with MORE unclassified instances at the next gap. Reverted (the work is saved:
`git stash` "capability-1 inline head-start" + `/tmp/capability1-inline-headstart.patch`,
280 lines). **Conclusion: inline is necessary but not sufficient — it must be paired with
closure-adaptor lifting (`.all`/`.any`/`.map` over a literal/pinned collection → quantified
body) and `&mut`-as-opaque, landed together, or it multiplies the work.** That is the
shape of the supervised capability-#1 session: inline + closure-adaptor + &mut-opaque as
ONE coordinated change, gated on unclassified actually dropping (not just shifting) and
the masked-contradiction guard.

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
