# Object identity and object-field-flow acceptance requirements

This note scopes the construction substrate required by the acceptance matrix in
`implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/`.
It deliberately specifies obligations, not a production representation.

## Required authority

An object occurrence needs a content-addressed identity whose CID is derived
from its authenticated construction testimony and construction locus. The
identity law is `h = h(p)`: equal authenticated construction preimages produce
the same identity and different construction occurrences produce different
identities. A source spelling, a variable name, a class name, or a symbolic
receiver is not an identity preimage.

A field place is the typed pair of an authenticated object identity and a field
selector. The selector participates in the place CID, but its spelling alone
grants no object authority. A field version additionally commits to the prior
field version, the constructed stored value, and the exact store occurrence.
This prevents two stores or two independently constructed objects from sharing
an accidental identity hub.

## One temporal model

Object identities and field versions must be values carried by the existing
source-tree substitution and `BindingState` flow. A name binding may carry an
authenticated object identity just as it carries any other constructed node.
An assignment alias copies that identity through the ordinary binding update;
there is no ambient heap table, global name map, desugar-time scope, or second
binding resolver.

Branching uses the existing guarded state. A field version available on only
one completion face must remain guarded on that face; a read after the join may
project it only under the corresponding guard. A halted face contributes no
store to later state.

## Alias and descriptor obligations

`alias = original` shares an identity only when the RHS construction already
carries authenticated object identity. Calls, imports without resolved
construction testimony, symbolic parameters, and other opaque projections do
not establish alias equivalence.

Before a store can become a field version, construction must establish the
applicable descriptor/`__setattr__` behavior. A data descriptor, dynamic
`__setattr__`, monkey patch, or unresolved class contract can redirect or reject
the store; those cases remain typed-loud. A later read likewise requires
authenticated lookup behavior compatible with the stored place. The model may
not replace Python descriptor semantics with a plain dictionary assumption.

An opaque call that can receive the object invalidates knowledge of mutable
fields unless the call contract proves the relevant frame condition. It is
unsound to retain a pre-call field value merely because the variable spelling
did not change.

## Total outcome

For every attempted object-field projection, construction has exactly two
outcomes:

1. an authenticated object/place identity and field version threaded through
   the existing temporal binding state; or
2. a typed construction gap naming the missing identity, alias, descriptor, or
   frame testimony.

There is no fabricated completion, name/vendor dispatch, ambient state, or
generic fallback value.

## Acceptance matrix

- `store-then-read`: the later read observes the constructed stored value;
  truthful is SAT and the lying twin is UNSAT.
- `distinct-objects`: two construction occurrences of the same class retain
  distinct identities and do not collide.
- `authenticated-alias`: a plain assignment alias shares the authenticated
  identity, so a store through one name is visible through the other.
- `version-flow`: a read before a later alias mutation remains the earlier
  immutable value while a read after the mutation observes the new version,
  including through a second authenticated alias.
- `distinct-version-flow`: alternating stores through aliases of two distinct
  construction occurrences never cross-link their version chains.
- `symbolic-receiver`: no identity can be minted from a formal/symbolic
  receiver; the flow remains typed-loud.
- `opaque-mutation`: a call without an authenticated frame contract may mutate
  the object; a later field read remains typed-loud.
- `opaque-alias`: an opaque function result does not inherit its argument's
  identity; reading through it remains typed-loud.

Every case has a renamed structural twin. The fixture audit rejects imports,
ambient binding declarations, stringly reflection, and type/name inspection so
no passing implementation can justify itself with a vendor or spelling gate.
