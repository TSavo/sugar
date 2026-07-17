# Sequential Dig Body Return Selection Design

## Live frontier

Current main (`60e26aea3`) replays the 17 class-B `SequentialDigBody`
timeout-ledger rows as:

| terminal | files |
| --- | ---: |
| `SequentialDigBody` | **8** |
| completed | 6 |
| distinct later loud owner | 3 |
| silent | **0** |

The eight live rows all request `reduced guarded returns with an unguarded
fallback`. Their reduced records contain guarded terminal outcomes followed by
an unguarded fallback return. `SequentialDigBody` already constructs
`GuardedReturn` plus fallback selection, but classifies `GuardedRaise` as an
unrecognized non-return contribution and panics before it reaches that fold.

## Design

Construct one total return-selection value from the reduced outcomes, in source
order:

- `GuardedReturn` contributes its reduced value under its reduced guard.
- `GuardedRaise` contributes an `ExceptionalExitValue` under its reduced guard.
  `ExceptionalExitValue` projects the same source-cited
  `py.exceptional_exit` term that `GuardedRaise.post_contribution` already
  testifies to; it does not invent a runtime effect or a Python value.
- The unguarded `ReturnValue` is the final fallback.
- Folding the guarded exits in reverse produces nested `GuardedValue` nodes,
  preserving first-terminal-wins semantics.

The construction consumes only reduced `GuardedReturn`, `GuardedRaise`, and
`ReturnValue` testimony. It never inspects pandas AST shapes. A contribution
containing state, support, an opaque record, an incomplete reduction, or no
unguarded fallback remains the existing loud `FactoryPanic`.

No RuntimeEffect constructor or allowlist changes. A genuine effect already
returned as `Incomplete` propagates unchanged through the existing path.

## Rejected alternatives

- Treat a raise arm as the ordinary fallback value: fabricates a return on an
  exceptional path.
- Drop guarded raises before folding returns: makes an assertion vacuous on the
  raise path and loses already-constructed exceptional-exit testimony.
- Inspect `If` or `Try` AST nodes: repeats the syntactic trust error and can
  disagree with the reduced semantic record.
- Mint a conditional RuntimeEffect: the outcomes are already constructed, so
  this would relabel unimplemented machinery as runtime dependence.

## Evidence

- Red discrimination: guarded raise plus unguarded return currently panics at
  `owner=SequentialDigBody`.
- Green discrimination: the same reduced outcomes construct
  `GuardedValue(guard, ExceptionalExitValue, fallback)`.
- Bad twin: guarded raise mixed with a state contribution remains a
  `FactoryPanic`.
- Verdict witness: a ground call taking the fallback return is satisfiable for
  the truthful assertion and unsatisfiable for the wrong result.
- Bounded replay: the eight named representatives conserve every terminal into
  completion or a distinct loud owner, with silent zero.
- The RuntimeEffect constructor-site census is unnecessary unless an effect
  site changes; this design changes none.
