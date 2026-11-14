# Linear `Outcome` to `ExitSet`: the conversion rules (#7825)

`ExitSet` (`Completed` / `Halted` arms) is the only result form (owner,
#6015; #7825). Every linear use below has a one-line `ExitSet` replacement.
Each helper's docstring in `exit_set.py` states the same rule. When a
directory is done, it contains no `Complete(`, `Incomplete(`, or
`isinstance(..., Complete/Incomplete)`. After that, `complete.py`,
`incomplete.py`, `outcome.py`, `collapse`, `outcome_to_exitset`, and
`sole_completed_outcome` are deleted.

| Linear form | `ExitSet` form |
|---|---|
| `Complete(v)` | `ExitSet.completed(v)` |
| `Incomplete(e)` | `ExitSet.halted(e)` |
| `Incomplete(e, (c1, ..., cn))` | `ExitSet.halted(e, guard=and_([c1, ..., cn]))` |
| `Incomplete(e).guarded(c)` | `ExitSet.halted(e).guarded(c)` |
| `isinstance(o, Complete)` | `o.completed_value() is not None` |
| `o.value` (after the `Complete` check) | `o.completed_value()` |
| `isinstance(o, Incomplete)` | `o.halts() == o.exits` (every arm halts) |
| `o.effect` (after the `Incomplete` check) | `h.effect for h in o.halts()` |
| `o.branch_conditions` | `h.guard` of each `h` in `o.halts()` |
| "can this step halt?" | `bool(o.halts())` |
| `isinstance(o, (Complete, Incomplete))` | `isinstance(o, ExitSet)` |
| `o.and_then(step)` | `o.and_then(step)`; once `step` answers `ExitSet` only: `o.sequence(step)` |
| `outcome_to_exitset(o)` | `o` (it is already an `ExitSet`) |
| `o.collapse()` | delete the call; read `o.completed_value()` / `o.halts()` where a linear shape was wanted |
| `factored_operand(o)` | `o.factor_completed()` |
| `Complete(v).follow()` / `.contribution()` / `.extend_scope(ctx)` | the value owns them: `v.follow_rest()` / `v.contribution()` / `v.extend_scope(ctx)` on `o.completed_value()` |

## Arms: `owed` (H4)

`Completed` and `Halted` carry `owed`, a tuple of items the proof must
carry as members (today: `unanswered_calls.UnansweredCallV1`). It is not
part of what an arm denotes: it is excluded from compare, hash, and repr,
and it never decides a merge or enters an enrolled CID.

**Every arm rebuild carries it.** A rebuild from one arm passes that arm's
`owed`. A rebuild from several arms (a merge, a sequence, a fan, a
factoring) passes `owed_union(a.owed, b.owed, ...)`. Never use the
intersection. Never drop it. A `Completed(guard, value)` or
`Halted(guard, effect, state)` built from an existing arm without its
`owed` drops a member of the proof. `ExitSet.collapse` keeps an owing arm
as an arm, because a linear outcome has nowhere to put the debt.

The reader is `ExitSet.owed_items()`, used through
`unanswered_calls.owed_calls(outcome)` on the reduction's final outcome.

Some arm rebuilds outside `exit_set.py` do not carry `owed` yet. They are
listed on the PR that introduced the slot. The converter that touches one
carries `owed` there.
