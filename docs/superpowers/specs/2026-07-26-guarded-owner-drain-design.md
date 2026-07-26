# Guarded Owner Drain Design

## Scope and measurement

Lane L3 drains only the first live Category-5 owner from the historical
`desugarConstructionPanics` board. The historical `guarded` set contains 25
occurrences in 18 files. A HEAD remeasurement through the authoritative
control-effect `_measure_file` door, with one demand table derived from the
full pandas 3.0.3 corpus root, finds 28 live `guarded` occurrences in those 18
files. Therefore `guarded` is the selected owner and `ground_index_error` is
out of scope.

## Floor law

Guarding has two constructed meanings in this owner family:

1. A pure value carrier with no invariant, postcondition, control effect, or
   scope transition is guard-stable. It returns the same content-addressed
   value when control places it under a branch guard. This is an explicit Floor
   category, not the `FloorValue` default; unknown values remain loud.
2. A `BlockValue` is a suite, not a pure carrier. Guarding it maps `guarded`
   over every statement and preserves its fall-through metadata. Each entry
   remains the sole owner of whether a guard is identity, implication, or a
   guarded control effect.

The live pure carriers are boolean literals, `StringValue`, `SymbolicValue`,
`ClassDefinitionValue`, and `ComprehensionValue`. Both boolean polarities opt
into the category even though only `True` occurs in the measured set.

## Discrimination

Truthful twins prove every enrolled pure carrier returns itself and that a
block guards its entries. Lying twins prove an `InvValue` becomes an
implication and a renamed unknown `FloorValue` still raises the exact
`owner=guarded` construction panic. No source name, pandas site, or function
spelling participates in dispatch.

## Acceptance

- Focused twins pass and fail if the new laws are removed.
- The same 18-file measurement reports `R_guarded = 0`, or survivors are
  attributed to a different named owner.
- Construction side-door and panic-catch floors remain zero.
- No residual count is pinned or accepted as a baseline.

