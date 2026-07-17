# Power Floor Evidence Design

## Goal

Retire the 12 current fatal-corpus `owner=power` terminals without treating an
opaque call result as a proven numeric value.

## Construction boundary

`TermValue ** OpaqueOpCallsite("len", ...)` has a concrete numeric base and an
independently warranted integer exponent. It constructs the existing native
`**` term coordinate and remains available to later equality evidence.

`CallSiteValue ** value` has no static numeric or `__pow__` warrant. It returns
`Incomplete(PowerRuntimeEffect)` authenticated at the real source fragment by
the complete `**(base, exponent)` operand term. Digging an available call body
may still redispatch to a more precise floor before this effect boundary.

All other unsupported power shapes retain the existing loud floor panic.

## Soundness discriminations

- Concrete powers continue to fold exactly.
- A concrete base with a `len(...)` exponent constructs the native coordinate.
- An opaque call-result base yields `PowerRuntimeEffect`, never `Complete`.
- Every runtime power effect carries a genuine source-site witness over both
  operands.
- PowerOpSugar's truthful witness remains satisfiable and its lying twin remains
  unsatisfiable through the real solver.

## Corpus receipt

Replay only the 12 named representatives retained by the fatal-corpus shards.
The required result is `owner=power` terminals `12 -> 0`, partitioned into
completed reports and files advancing to other loud named fronts.
