# Assertion-accounting ledger — total accounting over sugar's own tree

> **Rust measured (silent = 0).** Rust below (test-assertion lift axis) holds
> silent = 0 *structurally* and has its residual sorted to named bin-1 / bin-2 —
> the shape the finish-line metric wants. Python has no axis here (see the
> [Python section](#python-second-language)).

The companion axis to [`GOAL-sugar-proves-sugar.md`](./GOAL-sugar-proves-sugar.md).
That doc tracks **K** (panic-safe call sites discharged via sound reasoning,
measured by `sugar self-check` with the rust-analyzer oracle). This ledger
tracks the other half of "sugar proves sugar": the **lift homomorphism's total
accounting** — of every assertion in sugar's own test surface, how many lift to
FOL, how many are refused **by name**, and how many are **silently dropped**.

The hard invariant is the same one the whole product rests on: **silent = 0,
structurally.** Every `assert*` macro is either lifted to a FOL contract or
refused with a named reason; none vanishes.

## Recompute it yourself (no oracle, pure source)

```
cargo build -p sugar-lift-rust-tests --bin coretests_sweep
for c in libsugar sugar-ir-compiler-smt-lib sugar-cli sugar-verifier sugar-walk; do
  ./implementations/rust/target/debug/coretests_sweep \
    implementations/rust/$c/src --json /tmp/sweep-$c.json
done
```

`unaccounted (net)` mixes two signs; the load-bearing number is
`genuinely unreached (SILENT)` — a positive per-file residual, the true silent
drop. A negative residual is *inlining inflation* (one textual assert lifted as
several point-wise instances because a helper was inlined at N call sites), not
a drop. The sweep separates them.

## Opening baseline (main `e15b0ac00`, 2026-06-11)

| crate | asserts | lifted→FOL | refused (named) | SILENT | assertion-multiset CID |
|---|---:|---:|---:|---:|---|
| `libsugar` | 202 | 173 | 29 | 0 | `blake3-512:7c3a076104eab26fc178a2c3aef4a25bc21aa5b1d9c10306f015cf24d2fdb811fdb4ed592ed56a0beaad51656a3e35a3ecf4f4ba9ee6c94c67b95707e711988c` |
| `sugar-ir-compiler-smt-lib` | 250 | 229 | 21 | 0 | `blake3-512:f0115fdfb05215a389fb7882393fb7e733d0d483eec479759d49e6742e2d69bc5a2bab667c132c18b264fa4c9d9c5137f7f0067fc9dde5d2138044b41e17e516` |
| `sugar-cli` | 640 | 576 | 84 | 0 | `blake3-512:e1b035c232ceaac79528fac7a01ac84e119d0a9fbc364d445c98d422688ebada0d7fb88d64aa990633408e916ef49d351d4cfb3ac8a024b77ea382ed1315e3e0` |
| `sugar-verifier` | 395 | 309 | 86 | 0 | `blake3-512:e7f8583506f29f9c47390f6f872dafef08ad61b8adc569fad27fef3944ef0568642790347c2a52c3fd22e15481151d62b29de4fd4615406a541f3ecbcf087991` |
| `sugar-walk` | 1172 | 998 | 212 | 0 | `blake3-512:052afe9e0d9f4426953a193c8096c686ef795531bd4465286e7c1955993dd6b9c10464837c9f95f0046205e29364010d18b01597c705fc1e70f903f57b88ce07` |
| **total** | **2659** | **2285 (85.9%)** | **432** | **0** | — |

The multiset CID pins the assertion *surface*: a count-preserving swap still
moves the CID, so a silent regression cannot hide behind an unchanged total.

## The 432 named-refused, decomposed (the bin-1 burndown)

The construction-semantics axiom ([[project_provekit_construction_semantics_axiom]])
sorts every refusal into **bin-1** (constructed from literals, but the walker
doesn't speak that constructor yet — *drains*) or **bin-2** (never constructed
by the source — IO/clock/allocator, or here, procedural meta-test scaffolding —
*named, never proved*).

| category | count | bin | meaning / drain path |
|---|---:|---|---|
| **drainable term-shape** | 165 | bin-1 | `only scalar equality is liftable` (72), `unsupported term` (91). Teach the assertion lifter structural/componentwise equality and the missing term shapes. |
| **control-flow-released** | 115 | bin-1 | `assertion under for/if/match context … released to later pass` (88), `unenumerated statement position` (27). Drains when the loop/conditional assertion pass matures. |
| **temporal identity** | 81 | bin-1/bin-2 edge | `ambiguous temporal identity for receiver` — a mutated receiver has no value allocated-at-formation. SSA/guard-lifter tracking drains the stabilizable ones; genuinely mutated state is bin-2 by the allocation axiom. |
| **meta-test scaffolding** | 71 | bin-2 | sugar's own `assert_panic_locus_lines`, `assert_*_fails_closed`, `assert_kit_declaration_mappings`, etc. — procedural tests of the tooling itself, asserting about lift internals, not value constructions. Never FOL; named forever. |

**The single tracking number for this axis: drainable bin-1 = 280** (term-shape
165 + control-flow-released 115), with 81 on the temporal edge to be
adjudicated per the allocation axiom, and 71 honest structural bin-2.
**silent = 0 (hard invariant, held).** Drive drainable bin-1 → 0.

### Frontier correction (after slices 1–2): the 280 was over-counted

Reading the *actual refused corpus* (the `reason_samples`, not the bucket names)
collapsed the estimate. The two genuinely-cheap families — `matches!`
discriminant and struct-literal equality — are **drained** (slices 1–2). What
remains in the "term-shape" and "control-flow" buckets is **not** cheap bin-1:

- **iterator/closure predicates** (≈the entire residual `unsupported term`
  bucket): `coll.iter().any(|w| w["k"] == lit)`, `.all(|c| c == '0')`,
  `opt.map(|v| v.as_str())`. These quantify (∃/∀) over collections whose contents
  are **opaque runtime data**, not source literals. By the construction axiom,
  ∀-over-non-literal is **bin-2-leaning** — there is no finite construction from
  written literals to walk. Lifting the literal-collection sub-case
  (`for x in [a,b,c]`) is real bin-1 but rare in this corpus; the rest needs
  sound opaque-sorted `forall` encoding (substrate #1717), not a cheap term arm.
- **`for`-context** (83): every sample iterates an **opaque** collection
  (`for row in &report.rows`, `for solver in registry`) — same ∀-over-non-literal
  story. `released to layer 0` is an honest named refusal, not a silent drop.
- **temporal-identity** (81) and **meta-scaffolding** (71): unchanged —
  construction-boundary and bin-2 respectively.

**Honest revised number: cheap drainable bin-1 ≈ 0 remaining on this axis** —
the two clean families are harvested. The residual is (a) quantifier lifting
over opaque collections (hard, soundness-critical, much of it bin-2 by the
axiom), (b) temporal-identity via guard-lifter SSA, (c) bin-2 scaffolding named
forever. **silent = 0 throughout.** This is the expected shape of a converging
burndown: the cheap constructors drain fast, then the frontier is the genuinely
hard (quantifiers) and the genuinely IO/bin-2 (the membrane) — exactly the two
things the goal says should be all that's left.

### Next phase (the fork)

1. **Quantifier lifting** — sound opaque-sorted `forall`/`exists` over a
   collection term, so `coll.iter().all(|x| P(x))` lifts to `∀x. member(x,coll) → P(x)`
   and the literal-collection case unrolls. The biggest *real* bin-1 left, but
   soundness-critical (do not rush).
2. **Broaden to Python** (the second language) — see the
   [Python section](#python-second-language): sugar's own Python *test*
   assertions are lifted by no mechanism today.
3. **M1 closedness/vacuity gate** — make the existing `vacuous` label a *hard*
   structural refusal at mint (the precondition for an honest totality claim).

## Drain order (M3 worklist)

1. **Structural equality** — `only scalar equality is liftable` (72): lift
   `assert_eq!(a, b)` where `a`/`b` are structs / tuples / collections as
   componentwise equality, not just scalars. Biggest single bucket.
2. **Unsupported term shapes** (91): enumerate the distinct `unsupported term`
   shapes (`reason_samples` in the JSON ledger) and teach them one family per
   slice (the convergence pattern — each slice teaches one constructor).
3. **Control-flow-released** (115): the loop/conditional assertion pass picks up
   `for`/`if`/`match`-bound assertions as guarded point-wise rows.
4. **Temporal identity** (81): apply the guard-lifter SSA discipline
   ([[project_provekit_guard_lifter_soundness_pattern]]) to stabilize
   non-mutated receivers; name the genuinely-mutated remainder as bin-2.

Each slice updates this table with the new number and a one-line why, exactly as
`GOAL-sugar-proves-sugar.md` requires for K.

> Correction from the corpus read: the `only scalar equality is liftable` (72)
> bucket was **not** struct-`assert_eq!` — it was dominated by
> `assert!(matches!(x, Enum::Variant ..))`, a boolean discriminant assertion.
> Slice 1 drained it as such (below). Struct/tuple componentwise `assert_eq!`
> remains a later slice under "unsupported term shapes".

## Drain log

- **`matches!` discriminant lift** (slice 1, base main `4221ec1d1`): lift
  `assert!(matches!(x, Type::Variant ...))` as the construction-semantics
  discriminant atom `variant_of(x) == "variant::<tag>"` — the SAME atom
  panic-locus lifting emits, same teeth (two variants = two distinct string
  constants ⇒ UNSAT). Guards and binding / single-segment / or-patterns are
  **refused by precise name** (their discriminant is not unambiguous). Result
  over the 5 crates: lift **85.9% → 87.2%**; `only scalar equality is liftable`
  **72 → 10**; the unsound `matches!` shapes now read
  `matches! … not an unambiguous qualified variant` (15) and
  `matches! with a guard is not a pure discriminant` (13). **silent = 0** held.
  Negation (`!matches!`) fixed too: it previously fell to an opaque `macro:…`
  Var (a vacuous lift, no teeth); now lifts the negated discriminant.

- **struct-literal equality** (slice 2, base main `978c4996c`): give
  `translate_term_in_scope` an `Expr::Struct` arm so `assert_eq!(x, Type { f: v })`
  lifts the RHS as a Ctor `struct:<Path>` with one `field:<name>` sub-ctor per
  field, **sorted by name** (source field order irrelevant → canonical term) and
  field names significant. Distinct literals are distinct Ctors ⇒ asserting the
  wrong one is UNSAT (teeth). `..rest` is **refused by name** (value not fully
  pinned from the literal); an untranslatable field propagates its own named Err.
  Result over the 5 crates: lift **87.2% → 87.8%** (+16 lifted, −16 refused);
  `assert_eq!: unsupported term` **42 → 29**. **silent = 0** held.

## Python (second language)

Python's self-application does **not** go through the test-assertion lifter:
sugar's own Python tests use plain pytest `assert`, while
`assertion_layer`/`lift_test_file` target a vendor `assert_*` vocab learned from
testing modules (numpy.testing-style) — a different (vendor) surface. sugar's
own pytest `assert` statements are lifted by *no* mechanism today; a
plain-`assert` lifter is the Python analog of the Rust assertion sweep.

## Java (third language) — resolution: a thin kit, not a self-application corpus

The "across all three languages" clause does **not** map symmetrically. sugar's
*live* Java is **three files** — the kit RPC implementation under
`implementations/java/sugar-lift-java-tests/src/` (`JavaTestAssertionsRpc.java`,
`JavaPanamaFfmRpc.java`, `JavaJunitWitnessRpc.java`). Every `provekit-lift-java-*`
module directory is an **empty stub** (only a `target/` build dir survives), stale
from the pre-rename era.

Those three files are a **lifter**, not assert-bearing business logic. The Java
kit is exercised by the `run.sh` fixture suite (83 tests) lifting **vendor** Java
— that proves *the product works*, not *sugar proves its own Java*. There is no
Java `@Test`/`assertEquals` self-test corpus the way Rust has `#[test]` asserts.
So the Rust self-application axis has **no Java analog** — there is nothing of sugar's own Java for a Java assertion
lifter to lift.

Honest reading of the finish line, then: *sugar proves sugar wherever sugar has
substantial constructible code.* That is **Rust** (deep: `sugar-cli`/`libsugar`,
both the `coretests_sweep` assertion axis and the `sugar self-check` K axis).
Java's footprint is a thin kit, named as such;
its correctness is carried by the fixture suite, not by self-application. Forcing
a "Java self-application number" would be a hollow metric — the honest move is to
name the asymmetry, not manufacture symmetry.
