# Sugar Invariants

Sugar is the factory layer that turns source syntax into warranted ProofIR
testimony through lawful floors. These rules are construction law, not style
preferences.

The law is simple: recognize the source shape, construct typed children, reduce
recursively, delegate domain work to floors, and then produce exactly one of two
lawful outcomes: `Complete`, or `Incomplete` because of a real runtime
`Effect`. Every other scenario is a panic.

## Ontology: Recognition, Dispatch, Meaning

Sugar is not one pile of lifter code. It is three class/protocol hierarchies
joined by typed edges:

| Hierarchy | Authority | Must not become |
| --- | --- | --- |
| Sugar | recognition of source shapes, factory ordering, witness enrollment | semantics, floor inspection, ProofIR meaning |
| Floor | semantic dispatch over completed values | kind predicates, helper bags, side tables |
| ProofIR | claim shape, scoped obligations, denotation, verdict witnesses | source interpretation, vendor behavior, transport JSON |

These hierarchies are load-bearing. A violation is not merely bad style; it is a
false authority claim.

## Sugar Is Recognition

A sugar class recognizes source territory. Its recognizer answers only: "does
this source fragment belong to this sugar?" Its builder constructs typed child
bodies and records the ordered tower position. Its witness proves enrollment
through the production path.

A sugar may not decide semantic truth, duplicate a floor operation, inspect a
completed floor by species, or emit solver homework. Once source is recognized,
the sugar composes and collapses; meaning comes from floors and ProofIR.

## Floors Are Dispatch

A floor class is a completed semantic value with a dispatch surface. Operations
ask the value what the operation means for that value: `receiver.map_with(...)`,
`receiver.contains_with(...)`, `receiver.project_callsite_with(...)`, and so on.
The caller supplies operation intent and context; the floor owns the answer.

A missing arm is a floor construction gap with owner, blame, observed shape,
requested method, and fix. It is not a reason to add a kind ladder, `matches!`
probe, stringly status, or private side registry. Callers match the closed
result algebra, never the value species.

## ProofIR Is Meaning

A ProofIR node class owns the legal shape and denotation of a proof claim. It
owns scoped obligations (`pre`, `post`, invariants), warrants, RPC projection,
and truthful/lying verdict witnesses. Sugar routes source toward a node; floors
reduce values into testimony; ProofIR says what the emitted claim means.

No layer upstream of ProofIR gets to fabricate facts or leave unreduced source
syntax for the solver to interpret. The solver is a referee over typed testimony,
not a student of Python, Rust, numpy, pandas, or package re-export folklore.

## Edges Are Law

The legal edges are:

| Edge | Legal meaning | Forbidden drift |
| --- | --- | --- |
| Source -> Sugar | recognition and ownership | shadow ASTs, semantic inference |
| Sugar -> Floor | top-down tower collapse | recognizer doing floor semantics |
| Floor -> Value/Effect | closed dispatch result | silent swallow, fake incomplete, kind ladder |
| Floor/Sugar -> ProofIR | warranted testimony | fabricated facts, unreduced spelling, solver homework |
| ProofIR -> Solver | verdict over typed obligation | asking solver to recover vendor semantics |
| Sugar -> Witness | enrollment evidence | catalog entry with no production testimony |

When a regression appears at a boundary, ask which edge failed. If the edge can
honestly carry the invariant, promote it into the type/protocol/constructor
surface so the illegal state is unconstructable. If the boundary is genuinely
open, keep a content-addressed auditor membrane that names offender classes and
retirement paths.

## Towers Collapse From The Top Down

Recognition selects the ordered tower; reduction collapses it from the top down
through floor dispatch. No layer may skip downward, inspect below itself, or
build a second representation to avoid the tower. `comes_before` is architecture,
not sorting trivia: it defines which owner gets first lawful bite at a source
site.

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

## Builtin Macros Are Sugars

Compiler/std builtin macros such as `format!`, `format_args!`, `concat!`,
`cfg!`, `file!`, `vec!`, `write!`, and `writeln!` are source shapes owned by
dedicated sugars. They must be claimed before the generic macro fallback.

The generic macro fallback expands only visible source `macro_rules!`
definitions. A builtin macro with no visible `macro_rules!` source is a
construction gap and must panic until its sugar exists.

Builtin macro sugars construct typed children, compose those children, and
bubble child effects unchanged. They do not invent effects because the macro
body is not visible.

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
- Do not route compiler/std builtin macros through generic macro fallback.
- Do not make a broad sugar clever when a tiny sugar or floor visitor would do.
- Do not move behavior into `lib` merely because it is convenient from a call
  site.
