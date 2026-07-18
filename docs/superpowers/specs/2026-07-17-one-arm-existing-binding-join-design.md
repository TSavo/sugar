# One-Arm Existing-Binding Join Design

## Problem

`PredicateValue.binary_conditional` reduces both the condition and the body of
an `if`. For an `if` without an `else`, it currently records every changed
binding as conditional-only. That is correct for a name introduced inside the
branch, but wrong for a name already bound before the branch: the false path
retains the prior value, so the post-conditional value is fully constructible.

The remaining #5087 pandas representative reaches this case while reducing
`DatetimeArray._generate_range`: `unit`, `start`, and `end` already exist, and
the `unit is None` branch changes them. Failing to construct their false-path
values leaves a stale definite binding and eventually produces a
`SequentialDigBody` panic.

## Design

The factory will construct the post-conditional binding from reduced semantic
scopes, never from AST inspection:

- Compare the temporal scope before the branch with the reduced continuing
  branch scope.
- For every changed name that existed before the branch, answer both reduced
  values and emit a definite joined binding
  `GuardedValue(condition, branch_value, prior_value)`.
- For every name introduced only inside the branch, retain the existing
  guarded-binding behavior. Reading it outside an activated matching guard
  remains a loud `TemporalContext` panic.
- If either value answers `Incomplete`, preserve that incomplete testimony
  under the appropriate guard. Do not turn it into success or invent a runtime
  effect.

`GuardedFaces` already carries both `joined_bindings` and `guarded_bindings`,
so the change is confined to the reduced-scope selection in
`PredicateValue`.

## Soundness Boundary

The join is allowed only when the false-path value is present in the actual
pre-branch temporal scope. A branch-only name has no false-path value and
therefore cannot become definitely bound. Opaque or incomplete values remain
loud. This change adds no `RuntimeEffect` constructor and no empty-success
path.

## Verification

1. A focused discrimination test proves that a one-arm assignment to an
   existing binding yields `GuardedValue(condition, changed, prior)`.
2. The existing bad twin proves that a name introduced only inside the arm
   remains a loud `TemporalContext` panic.
3. A fresh `IfSugar` truthful/lying witness proves SAT/UNSAT for the constructed
   binding.
4. The named pandas business-hour representative is replayed on the final
   rebased commit, recording the `SequentialDigBody` terminal delta and where
   its mass moves, with silent count zero.
