# If Continuing-Path Join Design

## Goal

Construct bindings after nested `if` / `elif` / `else` from the paths that
actually continue, without treating a guarded raise on one path as if the whole
branch terminated.

## Measured front

Current main `497b865cc8f3bdd577fab8e43f2c179ef4b604a9` stops once in
`pandas/core/apply.py:666:15`:

```text
owner=TemporalContext observed=result requested=value
```

The enclosing conditional has two continuing outcomes that bind `result` and
one outcome that raises. The nested conditional reduces correctly, but its
`GuardedFaces` is flattened into a block record. `PredicateValue` then equates
"has any exceptional post" with "the whole branch exits" and discards the
continuing binding.

## Design

`BlockSugar` will retain one semantic bit on its constructed `BlockValue`:
`can_fall_through`. The bit is computed while reducing statements, from the
actual `FollowStep` returned by each reduced outcome. A halt makes the block
non-continuing; reaching the end makes it continuing. No AST is inspected.

`PredicateValue.binary_conditional` will derive `then_exits` and `else_exits`
from that block testimony. Existing scope construction then:

- joins both scopes when both paths continue;
- projects the sole surviving scope when exactly one path continues;
- carries no binding when both paths terminate.

`TrySugar` will use the same `BlockValue` testimony before its existing
fallback analysis, so the two control-flow owners cannot disagree about a
constructed block.

## Loudness and effects

This change adds no RuntimeEffect. A missing binding remains a
`TemporalContext` `FactoryPanic` when any continuing path lacks it. An
incomplete or runtime-dependent reduced outcome remains loud through its
existing owner. Ground invalid twins are not converted into effects.

## Verification

- Red/green discrimination: nested `if/elif/else` with one raising arm and
  bindings on every continuing arm becomes readable after the join.
- Bad twin: one continuing arm omits the binding and remains a named
  `TemporalContext` panic.
- Exhaustive terminal twin: all arms raise and the following statement remains
  unreachable.
- Existing branch-scope and try suites remain unchanged.
- The `IfSugar` truthful/lying witness reaches `sat` / `unsat`.
- Named representative moves from `TemporalContext(result)` to completion or a
  distinct loud named owner; silent remains zero.
