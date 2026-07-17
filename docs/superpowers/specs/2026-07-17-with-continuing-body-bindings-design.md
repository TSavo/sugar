# With Continuing-Body Bindings Design

## Scope

Retire the next decidable `TemporalContext` residual from #4696:
`pandas/tests/frame/methods/test_select_dtypes.py` binds `result` inside
`with tm.assert_produces_warning(...)` and reads it after the `with`.

This change does not claim the remaining `lib`, `_d`, or other
`TemporalContext` failures. Those stay loud under their actual owners.

## Evidence and root cause

`WithSugar` reduces its body under the entered context and returns the body's
`BlockValue`. Assignment support has an empty contribution; its evidence lives
in the terminal `TemporalContext`. Returning only contributions therefore drops
the body binding before the enclosing statement sequence reduces
`tm.assert_frame_equal(result, expected)`.

The body is non-raising and continues normally, so every execution that reaches
the post-`with` statement has executed the assignment. The binding is definite.

## Design

At the final `WithSugar` body:

1. Reduce the body normally and inspect the reduced outcome's continuation.
2. If the body does not continue, preserve the established outcome byte path and
   project no bindings.
3. If the body continues, obtain the terminal scope from `BlockSugar`'s reduced
   path outcome.
4. Compare that terminal scope with the context entering the body.
5. Append `ScopeRebind` support only for changed or newly constructed bindings.

The projection consumes reduced semantic evidence, never AST assignment shapes.
Nested context-manager `as` bindings are already present in the body input
scope, so this pass projects only bindings constructed by the body.

## Loud frontier

- A name absent from the reduced continuing scope remains a named
  `TemporalContext` panic when read.
- A binding whose source reduces to `Incomplete` remains that typed effect when
  read; the projection does not discard or replace it.
- A raising body continues through the existing `WithSugar.__exit__` suppression
  logic. This pass does not invent an `__exit__` contract.
- Returning bodies project nothing because their enclosing continuation is
  unreachable.

## Tests and receipt

- RED/GREEN discrimination: assignment inside a continuing `with` is visible
  afterward.
- Bad twin: a continuing `with` path without the assignment remains a named
  `TemporalContext(result)` panic.
- Existing raising/opaque context-manager tests remain unchanged.
- Update the production `WithSugar` witness to place the witnessed return after
  the `with`; truthful must prove SAT and the wrong twin UNSAT.
- Named representative replay:
  `pandas/tests/frame/methods/test_select_dtypes.py`,
  `TemporalContext(result) 1 -> 0`, either completed or advanced to a distinct
  loud named front.

