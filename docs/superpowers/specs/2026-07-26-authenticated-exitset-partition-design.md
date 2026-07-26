# Authenticated ExitSet Partition Testimony

## Goal

Make `ExitSet.factor_completed()` accept completed faces whose exclusivity was
authenticated by a real branch producer even after `ExitSet.normalize()` merges
equal destinations, while completed arms that merely spell `g` and `not_(g)`
remain a loud `ExitSetFactoringGap`.

This is the single `make_doc` factoring-gap mechanism measured at
`eee2c2edc`. The construction-panic mechanisms and stableZero remeasurement are
outside this change.

## Root cause

`GuardedProjection` binding reads create two genuine branch faces:
`when_true.guarded(g)` and `when_false.guarded(not_(g))`. Their immediate
`union()` normalizes. When both faces read the same value, normalization
correctly merges their destination and disjoins their guards.

The formula after that merge is weaker evidence than the producer had. A
surviving disjunct such as `not_(g) or h` is satisfiable alongside `g`; no
formula search at the factoring site can recover the original partition.
Changing the destination key to include the guard would merely suppress the
correct merge.

## Representation

Each exit may carry authenticated path testimony in disjunctive normal form:
a set of alternative paths, where each path is a set of opaque partition faces.
A face contains an opaque partition identity and one of two polarities.

The empty path means no producer-authenticated partition constraint. Formula
guards remain the emitted semantic guard; testimony is evidence used only to
justify transformations that require exclusivity.

A generic partition join is the only constructor that mints a partition
identity. It accepts a guard plus true and false `ExitSet` values, guards the
two sides, attaches opposite faces of the new identity, and unions them.
`GuardedProjection` binding reads use this constructor.

## Propagation

- `guarded()` preserves existing testimony.
- `sequence()` combines path alternatives as a Cartesian conjunction because
  both the prefix and following path occurred.
- `normalize()` keeps destination bucketing and guard disjunction unchanged.
  When equal destinations merge, it unions their path alternatives.
- constructors and transformations that do not authenticate a partition carry
  the empty path.

Testimony must never be inferred from formula appearance.

## Factoring law

Two completed arms are authenticated-exclusive exactly when every alternative
path from the left and every alternative path from the right contain opposite
faces of at least one shared partition identity.

`factor_completed()` uses that law. If any path pair lacks such testimony, it
raises `ExitSetFactoringGap`; there is no materializing fallback, cap, or
source-specific exception.

## Discrimination twins

The truthful twin constructs a real `GuardedProjection` read whose two faces
share an equal value, verifies normalization merged the destination, then
places that result in a multi-arm completed face that must factor. Removing
testimony from the equal-destination merge makes this test fail.

The lying twin constructs guards that look like `g` and `not_(g)` without using
the authenticated partition join. Factoring must refuse. Restoring formula-only
exclusivity makes this test fail.

Both tests exercise real production construction and assert the observable
factoring outcome or the named gap.

## Non-goals

- No recursive inspection inside `or` formulas.
- No guard-sensitive destination key.
- No product cap or materializing fallback.
- No observed-source special case.
- No construction-panic Floor work.
- No stableZero corpus rerun in this change.
