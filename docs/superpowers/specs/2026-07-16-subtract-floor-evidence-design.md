# Subtract Floor Evidence Design

## Goal

Retire the current 11-name subtract-floor representative set without assuming
that an opaque call result supports numeric or set subtraction.

## Construction boundary

A concrete numeric `TermValue` minus a `SymbolicValue` constructs the native
`-` term coordinate. A concrete `SetValue` minus another concrete `SetValue`
constructs the exact left-hand members absent from the right-hand set.

When either the right operand is an opaque call result or the left operand is a
runtime comprehension/native coordinate, Python's numeric, set, or reflected
subtraction dispatch is not statically known. These cases return
`Incomplete(SubtractRuntimeEffect)` authenticated by the complete
`-(left, right)` operand term at the genuine source fragment.

All remaining unsupported shapes retain the existing loud subtract-floor panic.

## Discrimination

- Numeric-symbolic subtraction produces the native coordinate.
- Concrete set difference produces exact members.
- Opaque call-result subtraction never produces `Complete`.
- Every runtime subtraction effect witnesses both operands and its real locus.
- The existing SubtractOpSugar truthful witness remains satisfiable and its
  lying twin remains unsatisfiable through the real solver.

## Receipt

Replay only the 11 retained names. Current main already advances one datetime
file to `python.factory/Match`; among the ten live `owner=subtract` terminals,
the required result is `10 -> 0`, with completed reports separated from files
advancing to other loud fronts.
