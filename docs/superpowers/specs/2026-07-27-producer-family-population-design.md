# Producer-family population predicate

## Decision

Producer-family membership has one production owner. A closed testimony value
contains only the native EffectBoundary kind, the body-root producer family,
and authenticated execution ownership: the body completed, the root producer
halted, a different producer halted before the root was reached, or ownership
remains undecided. The named predicate returns member, re-attributed, or
undecided. It cannot receive a manager symbol or a descendant-call flag.

An authenticated completed edge is positive testimony and remains a member for
both Raise and Warning boundaries. A missing matching halt proves nothing. A
halt owned by a child producer is re-attributed to that producer. An
unauthenticated or undecided ExitSet remains undecided and is never converted to
membership.

## Attribute correction

The historical Attribute counts used four different predicates:

- 41 excluded every Attribute with a descendant Call.
- 50 restored nine Attributes whose Calls only construct receivers.
- 51 additionally attributed `col("f", "string2").is_indexed` to Attribute,
  although `col()` halts before `.is_indexed` is evaluated.
- 53 additionally included two non-raising Warning-boundary bodies without
  recording why completion is positive membership testimony.

The written predicate admits the nine receiver-construction sites and the two
authenticated completed Warning sites, and re-attributes the one child-Call
halt. The resulting denominator is derived as 52, not selected as a target.

## Tests

Truthful and lying twins prove that changing manager spelling or adding a
receiver Call cannot change membership. A child-Call halt proves re-attribution.
A completed Warning boundary proves non-raising membership. Structural tests
inspect the complete predicate module and its closed dataclass fields, replacing
the shallow single-function constant check. A mutation changes the child owner
to the root and must make the re-attribution twin fail before being reverted.
