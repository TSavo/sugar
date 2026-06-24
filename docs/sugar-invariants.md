# Sugar Invariants

Sugar is the factory layer that turns Rust surface syntax into lawful ProofIR
floors. These rules are construction law, not style preferences.

## Numerous Dumb Sugars

Sugars are numerous, small, and boring. A sugar should claim a broad source
shape it owns, construct its children as typed `SugarBody` floors, and compose
those floors. Prefer numerous dumb sugars over a few clever sugars that carry
special-case knowledge.

## Complete Or Named Incomplete

A properly operating sugar has two terminal outcomes:

- `Complete`: it reduced to a lawful floor.
- `Incomplete(Effect)`: it hit a real, named effect boundary.

There is no third terminal verdict for "not implemented", "unclassified", or
"I do not know how to reduce this". A factory miss or unclassified source shape
is a gap path and must stay loud. It is not an effect and must not be laundered
as an incomplete runtime result.

## Effects Are Real Effects

A sugar does not invent an effect because its implementation is incomplete.
Effects are reserved for real source/runtime boundaries: mutation, runtime
arguments, reflection, type layout, temporal ambiguity, IO, and similar
semantic stops.

Most effects come from downstream children. A parent sugar usually just reduces
its children and propagates their `Incomplete(Effect)` unchanged. A parent owns
an effect only when that parent is the source construct that actually creates
the effect.

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

## Panic On Impossible Ownership

If a sugar is constructed for a source shape the Rust compiler would never allow
that sugar to own, the correct behavior is a loud gap/panic, not an invented
effect. The compiler is an axiom for this layer: we are not a Rust compiler and
we do not second-guess type validity.

If construction cannot build the required typed child floors, construction must
fail loudly. Do not construct a sugar with raw child syntax and reopen the
factory later from `desugar`.

## Floors Own Visitors

Floors own operations over their values. When a caller needs a floor-specific
operation, it dispatches through a visitor trait or equivalent floor-owned
interface. The caller supplies context such as "curry this parameter with this
argument"; the floor decides how its representation responds.

This keeps temporal rewriting, aliasing, currying, numeric semantics, string
semantics, boolean predicates, and literal decomposition in the place that owns
the value. Call sites stay dumb: they ask the floor, compose the answer, and
propagate any real effect returned by the floor.
