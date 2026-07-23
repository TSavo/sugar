# Guarded loop recurrence design

## Scope

Symbolic `For`, `AsyncFor`, and `While` construction uses the existing closed
`LoopConstructionV1` graph. It does not use `ForUniversalSugar`, bounded
unrolling, an executable callback, or a target-name-to-value map. Concrete
finite unrolling remains an optimization only when every transition is proven.

The same recurrence is the construction primitive for `ListComp`, `SetComp`,
`DictComp`, and `GeneratorExp`: generators are nested flat-maps, filters guard
the inner recurrence, yielded value testimony feeds the collection builder,
and exhaustion remains explicit.

## Runtime binding state

`LoopProjectedBinding` is a runtime `BindingState` variant carried only inside
the existing `BindingEntryV1`. It owns the loop target CID and the exact ordered
guarded completed faces projected from `LoopConstructionV1`. Each face retains
its completion kind, guard, and authenticated runtime binding state. It never
turns a CID into a value.

Block substitution constructs and sequences the loop before processing the
following statement. Its post-bindings are minted through the existing
`SubstitutionTraceBuilderV1`, so a downstream load consumes a
`LoopProjectedBinding` occurrence in the one temporal binding model. Missing
face testimony, an unsupported binder, or an unsealable state is typed-loud.

## Recurrence routing

The loop pre-state feeds the iterator step (`For`/`AsyncFor`) or test step
(`While`). Body fallthrough and matching continue faces feed the latch. Matching
break faces become guarded completed exits. Iterator exhaustion or a false
while test becomes `NormalExhaustion`, and only that face sequences through the
`else` body. Nonmatching and ordinary halted faces propagate outward. The
post-state is the guarded projection of all completed faces after `else`.

This preserves both faces of every guard and makes the recurrence history a
function of its authenticated predecessor history, `h = h(p)`.

## Comprehensions

Each generator consumes the predecessor builder state and flat-maps its
iteration recurrence into the next generator. Each `if` clause adds a guard:
the true face continues inward and the false face returns to the owning latch.
At the innermost level, constructed element testimony (or constructed key and
value testimony for dictionaries) advances the builder. Normal exhaustion is
required testimony for closing the builder. `GeneratorExp` retains the same
recurrence graph without claiming eager traversal.

## Instrument and acceptance

The first code artifact is a red, automated instrument with a live offender
count `R`. It recognizes old universal/fold substitution, ambient loop maps,
CID-to-value fabrication, and absent projected post-bindings. It names the
replacement as `LoopConstructionV1` plus `LoopProjectedBinding` and remains red
until all recognized offenders are zero.

Truthful and lying twins cover continue-to-latch, break-to-completed-exit,
exhaustion-to-else, halted propagation, guarded downstream consumption, nested
comprehension flat-map, filter guards, and typed-loud symbolic/unbounded input
after a reachable break. The final battleaxe comparison reports numeric base
and head `R`, timeouts, non-native red, and auditor errors; no zero is claimed
without a non-empty complete denominator.

## Invariants

There is one construction path and one runtime `BindingEntryV1` model. No new
side-door finding or panic catch is admitted. Hashes remain functions of their
preimages. Both guarded faces are retained. Every unsupported shape is
exhaustive or typed-loud. Timeout count must not increase.
