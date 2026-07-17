# Sequential Dig Terminal Raise Design

## Problem

`SequentialDigBody` constructs selections from reduced guarded returns and
raises when the fallback is an unguarded return. It does not recognize an
unguarded `RaiseValue` as the exact fallback, so two current NumPy files remain
loud after all successful guarded faces.

## Design

Treat a reduced terminal `RaiseValue` as `ExceptionalExitValue(effect)`, using
the same source-cited exceptional-exit coordinate already used for guarded
raises. Reverse-fold prior guarded exits over that fallback in source order.
Exclude `RaiseValue` from unrelated residue, while retaining the existing loud
rule for mixed state, incomplete outcomes, and no-fallback partitions.

No AST inspection, RuntimeEffect, or empty-success arm is added.

## Evidence

- Guarded successful return plus terminal raise selects the return or exact
  exceptional exit.
- Mixed terminal raise plus unrelated state remains loud.
- Truthful/lying solver witness refutes the wrong return.
- Both named NumPy representatives leave `SequentialDigBody` with `silent=0`.
