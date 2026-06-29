<!--
  Lifting rules — the soundness contract for kit/lifter authors. House rule:
  these are LAWS, not style. The writing-a-lift-adapter chapters teach the
  mechanics (walk the AST, emit IR, conformance); this page is the contract those
  mechanics must satisfy. A lifter that follows every chapter and breaks a rule
  here is unsound — and one unsound lifter is enough to poison the federation.
-->
# Lifting rules — the soundness contract

The [writing-a-lift-adapter](writing-a-lift-adapter/) chapters teach you how to
*build* a lifter. This page is what makes one *correct*. Soundness is the whole
federation: a `.proof` is only worth anything because anyone can recompute it and
reach the same CID, and that only holds if every lifter obeys these laws. A lifter
that passes conformance but breaks a rule here ships a hollow proof — worse than no
proof at all.

These are laws. If you can't satisfy one, **refuse loudly and name the gap** — never
paper over it.

## 1. Lift is a function, not a relation

One surface lifts to **exactly one** contract. Two parties lifting the same surface
MUST get the same contract — if a surface could lift two ways, the CID is unstable,
pinning is meaningless, and federation collapses. A kit may have *many* lifters (one
per distinct surface: tests, annotations, proptest…), but each surface is
deterministic: **one surface → one contract.** The forbidden thing is one surface →
two contracts. (This is why a bespoke `.invariant`-style second path is fatal.)

## 2. Walk or silence — raw AST is not a side door

You lift native source by **walking its AST**. You do **not** pattern-match strings,
regex the body, `javap`, or guess by naming convention. "It's source; we AST-walk it,
or we don't reason about it." The forbidden act is the middle — naming patterns to
*appear* to understand. A parent sugar never rebuilds a child by crawling raw child
AST; semantic children are factory-built values (see
[factory-sugar-floor](factory-sugar-floor.md)).

## 3. Lift structure, not types

You lift what the code structurally **does** (its construction and provenance), not a
type-checker's opinion about it. Attribute-safety, shape, value pinning — all are
structure + provenance problems, not type-oracle problems. Don't reach for a
type-inference pass to do a structural lift's job.

## 4. No bespoke contract language

The only path to ProofIR is a **lift of native source** — the tests, assertions,
annotations, and bodies the authors already wrote. Never invent a `sugar::*` tag, a
decorator, or a per-language contract DSL for authors to write against. Needing a new
dialect to author contracts in is the failure mode, not the feature.

## 5. An EUF dig needs teeth

An uninterpreted (EUF) lift of `call:f(args) == literal` is a **valid** universe dig —
you pin the vendor's stated fact and check coherence, you do not re-run `f`. But it is
only valid if it has **teeth**: a bad-twin (assert the *wrong* literal) must come back
UNSAT. `f(x) == g(x)` with no literal anchor is always-SAT — a fake dig that proves
nothing. Verify the bad-twin refutes; never accept "it's EUF" as sufficient.

## 6. Outcome is total — silent drop is forbidden

Every source site you claim leaves by **exactly one** path:

- a completed lift (a contract/term emitted), or
- an **earned effect** (a `Hit` — see rule 7), or
- a **loud refusal / construction gap** that names the owner, the blame locus, the
  observed shape, and the concrete fix.

There is no `None`, no silent skip, no best-effort fallthrough. `silent == 0` is a
structural guarantee, not a target — make bad construction unrepresentable in your
types, not something later code might ignore.

## 7. Effects must be earned

An **effect** (a `Hit`) is a *real* source property that destroys the timeless value
relation: IO, mutation, nondeterminism, dynamic dispatch, environment reads. Pure but
**unlifted** syntax is **not** an effect — it's a construction gap that should panic
for *"write more sugar/floor for this shape."* Refusing a pure shape merely because you
haven't written its sugar yet is a **fake refuse** (the inverse sin). Refuse for real
effects; panic-for-more-sugar for everything you simply haven't covered.

## 8. Byte-deterministic, conformance-clean

Your canonical IR must be **byte-identical** across runs, and for any concept shared
with another kit, byte-identical **across kits** (the CID *is* the identity). Pass the
[conformance harness](writing-a-lift-adapter/04-conformance-test.md); cross-adapter
parity fixtures are not optional. If your lift isn't deterministic, federation breaks
silently.

## 9. Never false-discharge

A contract without a **constrained universe** is the hollow `call:` that any output
satisfies — it proves nothing while looking green. The universe (the body desugared to
literals) carries the teeth, not the bare call. `false_discharges == 0` is a security
invariant: a hollow proof collapses the whole product back to "another green check."

---

**Rule of thumb:** if you're ever tempted to make a lift *appear* to work — guess a
pattern, drop a site quietly, accept an EUF lift with no twin, emit a contract with no
universe — stop and refuse loudly instead. A named gap is the to-do list; a hollow
proof is the bug the whole product exists to prevent.

See also: [writing-a-lift-adapter](writing-a-lift-adapter/) (the mechanics) ·
[factory-sugar-floor](factory-sugar-floor.md) (the recommended shape that satisfies
these cleanly) · [concepts](../explanation/concepts.md).
