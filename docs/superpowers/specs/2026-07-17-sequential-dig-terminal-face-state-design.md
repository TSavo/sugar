# Sequential Dig Terminal Face State Design

## Problem

`SequentialDigBody` keeps reduced guarded exits while walking toward an exact
terminal fallback. A `GuardedFaces` outcome may contain branch-local scope
testimony as well as a terminal return or raise. Today that state is treated as
a competing function result, so NumPy's `get_expected_stringlength` remains
loud even though the reduced outcome says the state belongs only to a face that
exits.

## Design

Consume only the reduced `GuardedFaces` control-flow testimony. When a face is
proven terminal, accept its guarded return or raise while treating scope
rebinds guarded by that same terminal face as branch-local implementation
state. Preserve support testimony and the pre-existing exact joined-binding
lane. A rebind on a continuing face, incomplete reduction, or any residue
without this semantic proof stays a `FactoryPanic`.

The selection continues to fold guarded exits over the exact terminal
`RaiseValue` fallback in source order. There is no AST inspection,
`RuntimeEffect`, or empty-success arm.

## Evidence

- A terminal guarded face with same-face local state contributes its exact
  return/exception selection.
- The continuing-face state twin remains loud.
- A truthful solver witness is satisfiable and its lying twin is unsatisfiable.
- The named NumPy representative leaves `SequentialDigBody` with `silent=0`.
