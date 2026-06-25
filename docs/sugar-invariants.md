# Sugar Invariants

Sugar is the factory layer that turns Rust surface syntax into lawful ProofIR
floors. These rules are construction law, not style preferences.

The law is simple: recognize the source shape, construct typed children, reduce
recursively, delegate domain work to floors, and then produce exactly one of two
lawful outcomes: `Complete`, or `Incomplete` because of a real runtime
`Effect`. Every other scenario is a panic.

## Numerous Dumb Sugars

Sugars are numerous, small, and boring. A sugar claims one source shape it owns,
constructs its children as typed `SugarBody` floors, and composes those floors.
Prefer many tiny sugars over one clever sugar with special-case knowledge.

A sugar is a source-shape expert, not a domain expert. Once it has recognized
the syntax it owns, it should mostly be wiring.

## Recognition Only Recognizes

Recognition answers one question: "does this sugar own this source shape?"

Recognition may inspect source syntax enough to make that ownership decision
and construct the sugar. It must not reduce child nodes, inspect completed
floors, classify child effects, or decide semantic outcomes.

Optional paths may ask the catalog whether a role recognizes a source site
before building it. Required children use the appropriate `build_*` operation.
If a required child cannot be built, that is a construction-law gap and must
panic.

## Construction Builds Typed Bodies

Construction must build typed child bodies up front. A parent sugar stores
`SugarBody<TermFloor>`, `SugarBody<CompositeFloor>`, or another typed floor
body for every expression it will later reduce as a child.

Raw syntax may be kept only for provenance, token keys, pattern metadata, or
literal syntax owned by that sugar. Raw syntax must not be stored as a deferred
child body that reopens the factory from `desugar`.

Construction does not decide. It does not peek at the child's result to choose
an outcome. It builds the graph; recursive reduction collapses it later.

## Complete Or Effect Incomplete

A properly operating sugar has exactly two terminal outcomes:

- `Complete`: it reduced to a lawful floor.
- `Incomplete(Effect)`: it hit a real, named runtime effect boundary.

There is no third terminal verdict for "not implemented", "unclassified", or
"I do not know how to reduce this". A factory miss or unclassified source shape
is a panic path. It is not an effect and must not be laundered as an incomplete
runtime result.

## Effects Bubble Unchanged

Most effects come from downstream children. A parent sugar usually reduces a
child and, if the child returns `Incomplete(effect)`, returns that same effect.

The parent must not catch, wrap, rename, stringify, broaden, or reclassify a
child effect. "Better wording" is not a reason to change effect ownership.
Neither is trying to make a caller's accounting easier.

Lawful shape:

```rust
match child.reduce(ctx) {
    Outcome::Complete(value) => compose(value),
    Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
}
```

Unlawful shapes:

- converting a child effect into the parent's effect;
- converting a gap into `Incomplete(Effect)`;
- converting "I cannot reduce this" into `RuntimeArgument`;
- catching an effect only to rebubble a different one;
- inventing a runtime boundary because the sugar is incomplete.

A parent owns an effect only when the parent source construct is the runtime or
semantic boundary that creates it.

## Effects Are Real Effects

Effects are reserved for real source/runtime boundaries: mutation, runtime
arguments, reflection, type layout, temporal ambiguity, IO, and similar
semantic stops.

A sugar does not invent an effect because its implementation is incomplete. If
the source is constructible but unsupported, write the sugar, add the missing
floor operation, or let the construction gap panic.

## Delegate To Floors

Sugars delegate floor decomposition to floors. They do not inspect a floor and
reimplement its operations by shape unless that sugar is the floor owner.

Examples:

- A string format sugar desugars its format-string and argument children, then
  composes the formatted string. Runtime arguments are effects of the argument
  floor, not of the format sugar.
- An iterator quantifier desugars the receiver sequence and predicate body, then
  curries and joins predicate results. Predicate effects belong to the predicate
  body or floor, not to the quantifier.
- A method/adaptor sugar does not carry a private table of every literal case
  when the receiver floor can answer by visitor dispatch.

If a sugar wants to match on ctor names, parse a term representation, duplicate
numeric/string/sequence semantics, or maintain a private table of literal cases,
that is evidence that the owning floor is missing a visitor.

## Floors Own Visitors

Floors own operations over their values. When a caller needs a floor-specific
operation, it dispatches through a visitor trait or equivalent floor-owned
interface. The caller supplies context such as "curry this parameter with this
argument"; the floor decides how its representation responds.

Every visitor trait is a denied special case. It is a door placed in the floor
so callers do not cut their own side doors through floor internals.

This keeps temporal rewriting, aliasing, currying, numeric semantics, string
semantics, boolean predicates, and literal decomposition in the place that owns
the value. Call sites stay dumb: they ask the floor, compose the answer, and
propagate any real effect returned by the floor.

## Side Doors Are Bugs

All source behavior enters through factory/catalog recognition. A thin router
may ask "does this role recognize this site?" before calling a builder, but
non-recognition is fallthrough, not a semantic verdict.

If the router needs behavior, write the sugar or add the floor visitor. Do not
hide behavior in the router. Do not turn non-recognition into a fake effect.
Do not special-case source syntax in `lib` when a small sugar can own it.

## Panic On Every Non-Effect Gap

Any path that is not `Complete` and is not `Incomplete` because of a real
runtime `Effect` must panic. The panic is the instrument that says the sugar
graph is missing construction law, ownership, or a floor operation.

If a sugar is constructed for a source shape the Rust compiler would never allow
that sugar to own, the correct behavior is a panic, not an invented effect. The
compiler is an axiom for this layer: we are not a Rust compiler and we do not
second-guess type validity.

If construction cannot build the required typed child floors, construction must
panic. Do not construct a sugar with raw child syntax and reopen the factory
later from `desugar`.

## Forbidden Moves

- Do not put domain logic in construction.
- Do not reduce children during recognition.
- Do not catch a child `Incomplete(Effect)` and return a different effect.
- Do not turn a factory miss into `Incomplete`.
- Do not use `RuntimeArgument` as an unsupported bucket.
- Do not inspect completed floors by shape unless this module owns that floor.
- Do not reopen the factory from `desugar` for child bodies.
- Do not make a broad sugar clever when a tiny sugar or floor visitor would do.
- Do not move behavior into `lib` merely because it is convenient from a call
  site.
