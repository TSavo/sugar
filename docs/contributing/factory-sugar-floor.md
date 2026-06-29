<!--
  Factory / Sugar / Floor — a DESIGN GUIDELINE for structuring a lifter, not a hard
  law. The laws are in lifting-rules.md. This is the shape the Rust kit converged on
  and the Python kit mirrors; it makes the laws (total accounting, no silent drop, no
  AST side-door) fall out by construction. Source: docs/superpowers/specs/2026-06-27-python-sugar-factory-floor-design.md.
-->
# Factory / Sugar / Floor — a lifter design guideline

This is a **guideline, not a law.** The hard laws a lifter must obey are in
[lifting-rules](lifting-rules.md). This page describes the *shape* the kits converged
on for organizing a lifter — the Rust kit first, mirrored into Python — because it
makes those laws **cheap to satisfy**: total accounting, no silent drop, and "no raw
AST side door" stop being things you remember to do and become things the structure
won't let you skip. You can build a lifter another way; this is the one we recommend.

The model is three roles with one boundary between each.

## Floor — completed semantic values

A **floor** is not a status (`warranted` / `refused` / `support`). It first means
*"this is no longer raw syntax"* — a **completed semantic value** a parent may operate
on: a `TermValue`, an `ArrayLiteral`, a `PredicateValue`, a `BodyUniverse`, a
`BuilderState`. The boundary is strict:

- a parent sugar receives **completed child bodies, never raw child AST**;
- a sugar produces a completed value, bubbles a real effect, or panics for a gap;
- ProofIR/FOL emission reads **completed values only**.

The floor is where desugaring bottoms out — at literals and finished terms, the
constrained universe the solver actually sees.

## Sugar — a recognized shape that owns its operation

A **sugar** claims one source shape (its recognizer), carries **typed child bodies**,
and exposes one tiny operation (`reduce`/`desugar`). Operations are **sugar-owned and
duck-typed**: the sugar passes a narrow operation object to the completed child value
and lets ordinary dispatch decide whether the value can do it —

```python
receiver = ArrayLiteral(items=(TermValue(1), TermValue(2)))
outcome  = receiver.map_with(MapOperation(mapper=lambda_body, owner="MapSugar"), ctx)
```

`MapSugar` owns *that this site is a map*; `ArrayLiteral` owns *whether a finite array
can be mapped*; the operation owns *how*. A missing capability is a **loud floor gap**
(`write more Floor for this construction…`), never a silent skip.

Note that **the same syntax can serve multiple roles** — a `Call` may be a term, an
assertion subject, a callsite fact, a precondition target, an effect site, or inert
support. The role belongs in the **factory request**, not in one global ordered
cascade that guesses.

## Factory — the broker, auditor, and denominator

The **factory** is not "the recognizers." It is the broker that routes each
`(source-site, role)` request to candidate sugars, selects one, and **records the
disposition**: locus, AST kind, source memento, role, candidates, selected sugar,
output floor, emitted fragment, effect/refusal reason. That ledger is the
**denominator** for progress — the total accounting against which `silent == 0` is
measured.

A site the factory can't yet build is **work, not ambience**: it is a loud,
stop-the-world panic — *"write more Sugar for this AST"* with the requested role,
observed shape, blame locus, and suggested module. That red is the **intended
instrument**, not a failure of design; each step teaches the factory one more sugar or
floor operation until the screaming set shrinks to a stable zero.

## How the three move together

- **Construction is post-order.** The deepest child sugar is built first; the parent is
  constructed with its typed child bodies *already inside it*. A parent is never born
  holding raw AST and a promise to ask the factory later — so if a child floor doesn't
  exist, parent construction simply can't complete (bad construction is unrepresentable,
  not merely discouraged).
- **Desugar transforms forward.** Reduction then walks the already-built chain
  inside-out: each sugar performs the one operation its shape owns and hands the
  transformed floor to its syntactic parent, until the outer sugar yields the final
  floor ProofIR consumes.
- **Outcome is total; effects are earned.** Every claimed site ends as `Complete(floor)`,
  `Incomplete(effect)`, or a panic — never `None`, never best-effort. A real effect (IO,
  mutation, nondeterminism) is `Incomplete`; pure-but-uncovered syntax panics for more
  sugar. (These are the law versions in [lifting-rules](lifting-rules.md) §6–§7.)

## The ownership line (where rendezvous lives)

The kit owns **language reality** — syntax, builtins, platform behavior, source/body
discovery, and native→ProofIR emission. The Rust CLI owns **rendezvous**: proof
envelopes, canonical ProofIR transport, solver plans, witness recomputation, and z3
verification. The CLI must never learn a Pythonism (or a Java-ism); if a behavior needs
to know what `len`, `range`, descriptors, or broadcasting *mean*, that knowledge lives
in a kit sugar or floor, never above the RPC line. Everything above that line is the
one content-addressed form, which is exactly why the CLI stays language-blind and the
proof can rendezvous at a single CID.

---

Detailed worked instance (Python): the source spec at
[`docs/superpowers/specs/2026-06-27-python-sugar-factory-floor-design.md`](../superpowers/specs/2026-06-27-python-sugar-factory-floor-design.md)
(floor set, factory roles, effect set, proof obligations).
See also: [lifting-rules](lifting-rules.md) · [writing-a-lift-adapter](writing-a-lift-adapter/) · [writing-a-kit](writing-a-kit/).
