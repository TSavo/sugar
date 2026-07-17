# Power Floor Evidence Design

## Goal

Retire the 12 current fatal-corpus `owner=power` terminals without treating an
opaque call result as a proven numeric value.

## Construction boundary

`TermValue ** OpaqueOpCallsite("len", ...)` has a concrete numeric base and an
independently warranted integer exponent. The same is true for a guarded pair
of integer exponents and for `iter_elem(range(...))` when every range bound is
itself an integer literal or `len(...)` coordinate. These cases construct the
existing native `**` term coordinate and remain available to later evidence;
they never invent the active runtime integer.

`CallSiteValue ** value` has no static numeric or `__pow__` warrant. It returns
`Incomplete(PowerRuntimeEffect)` authenticated at the real source fragment by
the complete `**(base, exponent)` operand term. Digging an available call body
may still redispatch to a more precise floor before this effect boundary.

All other unsupported power shapes retain the existing loud floor panic.

## Soundness discriminations

- Concrete powers continue to fold exactly.
- A concrete base with a `len(...)`, guarded-integer, or warranted
  `iter_elem(range(...))` exponent constructs the native coordinate.
- An opaque call-result base yields `PowerRuntimeEffect`, never `Complete`.
- Every runtime power effect carries a genuine source-site witness over both
  operands.
- PowerOpSugar's truthful witness remains satisfiable and its lying twin remains
  unsatisfiable through the real solver.

## Corpus receipt

Replay only the 12 named representatives retained by the fatal-corpus shards.
The required result is `owner=power` terminals `12 -> 0`, partitioned into
completed reports and files advancing to other loud named fronts.
