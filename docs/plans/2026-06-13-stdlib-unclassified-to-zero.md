# Drive stdlib `unclassified` → 0 (rust 1.96.0 coretests)

> Sugar in, constraints out, or refused with reason.
> Logic is invariant; sugar dissolves away.

This is the goal, rewritten to completion after the doctrine locked.

---

## 1. The principle (locked)

**stdlib IS Rust sugar.** There is no special "stdlib layer." Every library is
sugar written *against* stdlib; stdlib is the floor; below it sits only the
**axiomatic compiler literals** and the construction axiom. `0u8` *is* 0,
`'a'` *is* 'a', `[a,b,c]` *is* that construction — the compiler asserts these as
ground truth and nothing reduces them further. That is the entire TCB.

Every assertion is decided by **one predicate**:

> **Does it bottom out in compiler literals — written, or synthetic-but-warranted —
> after desugaring via stdlib?**
>
> - **Yes → DIG.** The values are *available for constraint*. Emit the finite
>   conjunction (the universe). Discharged, warranted.
> - **Monkey business anywhere** (a side effect, IO, a runtime input, an opaque
>   receiver, a non-const closure) **→ BAIL.** Refuse with a damn good reason — a
>   clean terminal closure. The happy case.
> - **Nothing in between.** Everything bottoms out in desugared literals, or it
>   does not exist in our world.

DIG and BAIL are not two mechanisms; they are the two outcomes of the one
predicate. A wrong BAIL is a safe under-claim (we just didn't prove it). A wrong
DIG is a **fake-discharge** — the unsound direction. Therefore every reduction is
**exact-or-bail**: faithful to the language's semantics, or `None`.

A universe is warranted by its **fixed points**; a fixed point grounds in
literals. **No fixed point → no universe warrant.** Over a *constructed* (finite)
domain the universe IS the finite conjunction — `∀x∈{e₀…eₙ}. P(x) ≡ P(e₀)∧…∧P(eₙ)`,
no quantifier needed (the construction axiom). The vendor's `.fold(0,|i,&x|{…})`
over `[0..8]` is 9 fixed points; the law `∀k. xs[k]==ys[k]` they warrant *is* that
conjunction. Same object, three sugars.

---

## 2. How we desugar (locked)

**Desugar `fold` with `fold`.** stdlib is the desugarer: its own source
definitions ARE the reduction rules.

```rust
// Iterator::fold, verbatim from core — this IS the desugaring of `.fold`:
let mut acc = init;
while let Some(x) = it.next() { acc = f(acc, x); }
acc
```

We do not *model* `fold`/`filter`/`map`; we **inline their definitions**. The only
sound way to *not* model stdlib is to *keep* it: building `--no-std` is precisely
the move that would strip the definitions and force us to describe them (the next
thing to get subtly wrong — the no-vendor trap). With std in scope (we ingest
`rust-src` as *source*, never binaries), the axiom is present, so we apply it.

This is **hermetic** — in-process reduction, no `rustc` compile/run in the loop.
(Compiling-and-running real stdlib was the scaffold that revealed the answer; the
in-process *defolder* is the answer.)

**Synthetic literals are honest.** `filter([0..8], even)` produces `[0,2,4,6,8]` —
a value the vendor never typed. That is fine: it is **warranted by a
SourceMemento** (the filter call + the input literal + the predicate). The
synthetic literal inherits the warrant of the sugar that minted it. Synthetic
`4` is warranted by sugar `[0..8]` + the stdlib sugar that produced it.

**The sugar ≠ the lift.** The *sugar* is the source AST (the vendor's expression,
with its spans). The *lift* is the derived artifact (synthetic literals +
constraints, content-addressed, warranted back to the sugar). Two distinct
objects; the SourceMemento is the rope tying the lift to the sugar that warrants
it. **Every emit is warranted against a SourceMemento** — a constraint no source
line warrants cannot be emitted; the warrant is the precondition of emitting.

---

## 3. The engine — a `Sugar` hierarchy of responsibility

The doctrine, reified as a type. Stop hand-coding per-construct detection; model
the sugar as a **composite tree of `Sugar` nodes, each owning its own
`.desugar()`** (the Interpreter pattern; chain of responsibility falls out of the
composition):

```rust
trait Sugar { fn desugar(&self, ctx: &Ctx) -> Option<(Desugared, SourceMemento)>; }
//                                              ^^^^ None = monkey business → BAIL

LiteralSugar(arr | range | int | char | …)  // BASE CASE: desugar() = Some(literals). Written OR synthetic. The floor.
IterSugar(inner)                            // = inner.desugar()
FilterSugar(inner, pred)                    // = inner.desugar()?.retain(|e| const_eval(pred, e)?)   // synthetic, warranted
MapSugar(inner, f)                          // = inner.desugar()?.map(|e| const_eval(f, e))
FilterMapSugar / SkipSugar / TakeSugar / SkipWhileSugar / FlatMapSugar / EnumerateSugar / RevSugar(inner, …)
FoldSugar(inner, init, body)                // = thread acc over inner.desugar()?; emit body asserts as constraints
RFoldSugar = FoldSugar over the reversed sequence
ForEachSugar = FoldSugar< acc = () >        // for_each is fold with the unit accumulator
```

The parser turns the method-call chain into the nested tree
(`FoldSugar(FilterSugar(IterSugar(LiteralSugar([0..8])), even), 0, body)`);
`.desugar()` recurses inward; the warrant composes inward; the recursion **bottoms
out at `LiteralSugar` or some node returns `None` and the `?` propagates the
bail**. The structure *enforces* the predicate: the only way to produce a
`Desugared` is to reach literals through every layer (no fake-discharge), and any
layer's `None` is a happy refuse. **Adding a construct = adding one class with one
`.desugar()`.**

`Desugared` is a **(value, warrant)** pair, not a bare value — synthetic literals
carry the composed SourceMemento of the sugar that minted them.

### 3.1 Two invariants the design holds

**Breadth, not depth.** Exact-or-bail has no middle — a class either fully reduces
to literals (dig) or names its order-loss boundary (refuse); there is no "handle
80%, special-case the rest," and that partial-handling path is exactly where
lifters usually accrete depth. So complexity has nowhere to pool. The only growth
vector is breadth: a new construct is one new bounded class on the same
`decompose → desugar()` spine, touching no existing class (O(1) per class, no
O(n²) entanglement). The worst case is "not enough sugar added yet," never "the
sugar tangled into something we can't reason about." This makes the campaign a
breadth problem (enumerate constructs, add a class each) and safe to
parallelize / hand to agents — each class is small, exact-or-bail, adversarially
testable, warranted; the structure raises the floor instead of trusting the
contributor.

**Lift and replace — one engine, never parallel.** Each `Sugar`/`SideEffect` class
SUBSUMES the existing procedural lifting for its construct, and the old procedural
code is DELETED (the defolder port removed ~430 lines of `try_lift_*`). We do not
run a Sugar engine alongside the old procedural lifter — we migrate the lifter
INTO the hierarchy. End state: the whole lifter IS the `Sugar`/`SideEffect`
decomposition; everything procedural becomes a class; nothing lifts twice. Drain
the whole swamp until every construct decomposes into sugar.

---

## 4. It generalizes (this will be fun)

`Sugar` is **language-agnostic**. The engine is not Rust-specific:

- `FoldSugar` / `FilterSugar` / … — Rust iterator sugar over `core`.
- **`ListComprehensionSugar`** (`[f(x) for x in xs if p(x)]`) — Python sugar over
  Python builtins; desugars to the same filter+map+loop construction.
- `StreamSugar` (`stream().filter(…).map(…).collect()`) — Java sugar over the JDK.

All implement the same `trait Sugar`, all `.desugar()` via their *own* language's
definitions, all bottom out in *that language's* compiler literals + the
construction axiom, all warranted by a SourceMemento. They reduce to the one logic
floor and **federate at callsites by EUF** (no hub, no cross-language transport).
"stdlib is just sugar" is the special case of "every language's builtins are just
sugar."

---

## 5. Completion criterion

- Hermetic coretests sweep (rust 1.96.0): **`unclassified` = 0** — every assert is
  DIG (discharged, warranted against a SourceMemento) or BAIL (refused, a source
  property).
- Invariants held throughout, per push, gated in CI by `coretests-invariants.json`
  (exact match):
  - `assertion_multiset_cid` conserved =
    `blake3-512:ee0c6d92a4aa44f2f43bb657b70d9b87ba202392a6ea5c2aee519197e02aa59f6a3a425b49f7aa00191688e57c48bb795b58f74b35a2518cb6d4465eeb000a50`
    (we change classification, never the assert *sites*).
  - `SILENT = 0` (total accounting — nothing silently dropped).
  - Direction guard: `unclassified` never increases push-over-push.
- When the floor (stdlib) is closed, every library above it reduces through the
  same engine — its asserts can only bottom out in a node already classified.

---

## 6. Status

| stage | discharged | refused | unclassified | unaccounted | SILENT |
|---|---|---|---|---|---|
| #2161 base | 5694 | 327 | 394 | −98 | 0 |
| easy-refuses (#2162) | 5698 | 340 | 383 | −104 | 0 |
| defolder floor (`feat/fold-closure-foralls`) | 5696 | 367 | 352 | −98 | 0 |

- **easy-refuses (#2162):** terminal whitelist — `mutable container is not
  temporally stable`, array-repeat `not a finite construction`. The +4 discharged
  is sound inlining-unblock (the monotonic gate), not a false-discharge. CI-red
  only on the pre-existing panama showcase.
- **defolder floor:** `for_each`/`fold` bounded-universal lift + happy-refuse of
  opaque-receiver / side-effecting-body / opaque-accessor closures (40 terminal +
  2 defolded). CID conserved, SILENT 0. **Dig-completion in flight:** extend to
  transforming adaptors (`filter`/`map`/`skip`/…) by const-evaluating their
  closures over the literals — exact-or-bail.
- **Consolidation:** refactor the procedural defolder + the existing
  `try_lift_*_forall` machinery into the `Sugar` hierarchy.
- **Orthogonal main-red (do not block on it):** panama bad-suite needs the same
  EUF-identity match at the verifier's consistency-grouping key (not just the Java
  edge lifter); plus ~6 pre-existing `test-showcases` regressions rooted in the
  #2138 arc. Fix forward.
