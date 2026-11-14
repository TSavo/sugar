# `ExitSet` is the only result form (#6015, #7825)

`ExitSet` (`Completed` / `Halted` arms) is the only result form (owner,
#6015). The linear form and every bridge into `ExitSet` are deleted
(#7825): there is no second result class, no conversion into an
`ExitSet`, and no projection of an `ExitSet` back onto a linear shape.

Read a result through its own methods:

| Question | `ExitSet` form |
|---|---|
| one unconditional completed value | `o.completed_value()` (else `None`) |
| does every arm halt | `o.halts() == o.exits` |
| can this step halt | `bool(o.halts())` |
| the halted effects | `h.effect for h in o.halts()` |
| a halt's branch condition | `h.guard` |
| continue on every completed arm | `o.and_then(step)` / `o.sequence(step)` |
| factor an operand's completed arms | `o.factor_completed()` |

## Arms: `owed` (H4)

`Completed` and `Halted` carry `owed`, a tuple of items the proof must
carry as members (today: `unanswered_calls.UnansweredCallV1`). It is not
part of what an arm denotes: it is excluded from compare, hash, and repr,
and it never decides a merge or enters an enrolled CID.

**Every arm rebuild carries it.** A rebuild from one arm passes that arm's
`owed`. A rebuild from several arms carries the union of their debts, and
outside `exit_set.py` that union is never written by hand (#7825): a step
and what follows compose through `ExitSet.sequence` (with `consume=` for a
halt the composition owns), sibling arms that stand for each other merge
through `ExitSet.union` / `normalize`, and what a set of arms owes together
is read with `ExitSet.owed_items()`. The union itself (`_owed_union`) is
private to the exit algebra. Never use the intersection. Never drop it. A `Completed(guard, value)` or
`Halted(guard, effect, state)` built from an existing arm without its
`owed` drops a member of the proof.

The reader is `ExitSet.owed_items()`, used through
`unanswered_calls.owed_calls(outcome)` on the reduction's final outcome.

Some arm rebuilds outside `exit_set.py` do not carry `owed` yet. They are
listed on the PR that introduced the slot. The change that touches one
carries `owed` there.
