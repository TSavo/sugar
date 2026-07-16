# Try Continuing-Path Temporal Bindings Design

## Problem

The current Python lift drops temporal bindings constructed inside a `try`
body before reducing the enclosing block's continuation. `AssignSugar`
constructs the binding correctly, but `TrySugar` calls `body.reduce(ctx)` and
keeps only record contributions. Since a `BoundVar` contributes no report row
and carries its binding through the terminal reduction scope, the binding is
lost. A later `NameSugar` therefore reaches a loud `TemporalContext` gap.

The dominant #4696 reproduction is pandas `date_converter`: `result` is bound
by a call in the try body; both exception handlers return; only the normal try
path reaches `isinstance(result, DatetimeIndex)`. The continuation must see the
actual binding constructed on that surviving path.

## Approved Architecture

`TrySugar` will reduce every path once and retain both its record and terminal
scope. It will determine continuation from the reduced path outcome, never by
inspecting AST statement kinds.

The continuing-path set consists of:

- the normal try-body path when its reduced outcome falls through;
- each reduced handler path that falls through;
- the `else` path when present and falling through after normal completion;
- the `finally` path after applying its reduced control-flow result.

Bindings propagate only when present on every continuing path. A single
continuing path may carry its constructed binding directly. Multiple paths with
the same binding carry it directly; differing completed values join through the
existing guarded-value construction when an exact path guard exists. A missing
binding on any continuing path remains absent, so its later use produces the
existing named `TemporalContext` gap. Runtime-dependent continuation or a join
without an honest guard remains a named typed effect/gap; it never becomes a
silent binding or partial report.

`TrySugar` returns the joined bindings as ordinary scope effects in its reduced
outcome, allowing `BlockSugar` to thread them into the actual continuation.
`TemporalContext` itself remains strict and unchanged.

## Tests

- A good control assigns inside `try`, has terminal handlers, and reads the
  binding afterward. Its truthful assertion must lift and its lying twin must
  remain discriminating.
- A bad control has a handler that falls through without the binding. Reading
  the name afterward must retain the named `TemporalContext` gap.
- A multi-continuation control constructs the same binding on every continuing
  path and proves the join is derived from reduced scopes.
- Existing try/except tests remain unchanged and green.
- The production representative
  `pandas/io/parsers/base_parser.py` must complete with real facts.
- The fatal census is rerun and compared with the #4696 baseline of 241
  `TemporalContext`-owned fatal files. The observed reduction is the reported
  Delta; no inferred or extrapolated count is accepted.

## Scope and Safety

This change does not catch `FactoryPanic`, preseed names, synthesize ambient
values, emit partial reports, weaken `TemporalContext`, or change verifier
behavior. It constructs only bindings testified to by reduced paths. Remaining
unsupported paths stay loud.

Part of #4696. This design does not close or fix the issue.
