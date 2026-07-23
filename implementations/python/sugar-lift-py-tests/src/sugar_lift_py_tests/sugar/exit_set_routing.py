"""Shared ExitSet helpers for Try and With contract routing.

Promote embedded guarded raises out of Completed blocks, and project an
ExitSet back to the linear BlockValue Outcome consumers still speak.
"""

from __future__ import annotations

from dataclasses import replace

from sugar_lift_py_tests.outcome import Complete, Outcome


def is_hard_raise(entry) -> bool:
    """True when entry is a raise Incomplete that halts control flow."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    if not isinstance(entry, Incomplete):
        return False
    if not isinstance(entry.effect, (RaiseEffect, GroupedRaiseEffect)):
        return False
    return not entry.follow().continues


def guard_from_conditions(exit_guard, branch_conditions):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    parts = []
    if exit_guard is not None and exit_guard != true_guard():
        parts.append(exit_guard)
    parts.extend(branch_conditions)
    if not parts:
        return true_guard()
    if len(parts) == 1:
        return parts[0]
    return and_(list(parts))


def promote_raise_halts(exits):
    """Lift Incomplete(raise) entries out of Completed blocks into Halted exits.

    ``if c: raise`` flattens through IfSugar into a single Completed whose
    entries embed ``Incomplete(..., branch_conditions=(c,))``. Without this
    promotion, contract/handler routing cannot see a Halted face and the
    complementary completion path is lost under a linear adapter.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    promoted: list = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            promoted.append(exit_)
            continue
        if not isinstance(exit_, Completed):
            promoted.append(exit_)
            continue
        state = exit_.value
        if not isinstance(state, _ReducedBlock):
            promoted.append(exit_)
            continue

        remaining: list = []
        saw_halt = False
        for entry in state.entries:
            if is_hard_raise(entry):
                saw_halt = True
                guard = guard_from_conditions(exit_.guard, entry.branch_conditions)
                promoted.append(Halted(guard, entry.effect, state))
            else:
                remaining.append(entry)

        if not saw_halt:
            promoted.append(exit_)
            continue

        if remaining or state.can_fall_through:
            promoted.append(
                Completed(
                    exit_.guard,
                    replace(state, entries=tuple(remaining)),
                )
            )
    return ExitSet(tuple(promoted)).normalize()


def exitset_to_outcome(exits) -> Outcome:
    """Collapse ExitSet to the linear Complete(BlockValue) / Incomplete view."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    from sugar_lift_py_tests.outcome import Complete as OutcomeComplete

    collapsed = exits.collapse()
    if isinstance(collapsed, Incomplete):
        return Complete(BlockValue((collapsed,), can_fall_through=False))
    if isinstance(collapsed, OutcomeComplete):
        value = collapsed.value
        if isinstance(value, _ReducedBlock):
            return Complete(
                BlockValue(
                    value.entries,
                    fall_through=value.fall_through,
                    can_fall_through=value.can_fall_through,
                )
            )
        if isinstance(value, ReturnValue):
            return Complete(BlockValue((value,), can_fall_through=False))
        return Complete(BlockValue((), can_fall_through=True))

    entries: list = []
    can_fall = False
    for exit_ in exits.normalize().exits:
        if isinstance(exit_, Halted):
            inc = Incomplete(exit_.effect)
            if exit_.guard != true_guard():
                inc = Incomplete(exit_.effect, branch_conditions=(exit_.guard,))
            entries.append(inc)
        elif isinstance(exit_, Completed):
            value = exit_.value
            if isinstance(value, _ReducedBlock):
                if exit_.guard != true_guard():
                    entries.extend(
                        entry.guarded(exit_.guard) for entry in value.entries
                    )
                else:
                    entries.extend(value.entries)
                can_fall = can_fall or value.can_fall_through
            elif isinstance(value, ReturnValue):
                if exit_.guard != true_guard():
                    entries.append(value.guarded(exit_.guard))
                else:
                    entries.append(value)
    return Complete(BlockValue(tuple(entries), can_fall_through=can_fall))


def routed_entries_to_exitset(entries: tuple, guard, *, prior_state=None):
    """Project a linear route result under ``guard`` back into an ExitSet.

    Hard raises become Halted; remaining entries (facts, warnings, body
    residue) ride as Completed under the same guard.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    remaining: list = []
    out: list = []
    for entry in entries:
        if is_hard_raise(entry):
            out.append(Halted(guard, entry.effect, prior_state))
        else:
            remaining.append(entry)

    can_fall = not out
    if prior_state is not None and isinstance(prior_state, _ReducedBlock):
        fall_through = prior_state.fall_through
        transforms = prior_state.transforms
        if not out:
            can_fall = prior_state.can_fall_through or True
    else:
        fall_through = ()
        transforms = ()

    if remaining or not out:
        out.append(
            Completed(
                guard,
                _ReducedBlock(
                    entries=tuple(remaining),
                    can_fall_through=can_fall,
                    fall_through=fall_through,
                    transforms=transforms,
                ),
            )
        )
    return ExitSet(tuple(out)).normalize()


def site_inv_values(entries: tuple, site) -> tuple:
    """Stamp ``site`` on InvValues that arrived without one."""
    from dataclasses import replace as dc_replace

    from sugar_lift_py_tests.floor.inv_value import InvValue

    return tuple(
        dc_replace(e, site=site) if isinstance(e, InvValue) and e.site is None else e
        for e in entries
    )


def sugar_outcome_to_exitset(outcome) -> "ExitSet":
    """Project one sugar ``Outcome`` into a (usually single-exit) ExitSet.

    Used for tree-owned enter/exit method-coordinate sugars: Incomplete → Halted,
    Complete → Completed. Multi-exit Outcomes are not produced by a single
    method call desugar today.
    """
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome import Complete, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(outcome, Incomplete):
        if outcome.branch_conditions:
            condition = (
                outcome.branch_conditions[0]
                if len(outcome.branch_conditions) == 1
                else and_(list(outcome.branch_conditions))
            )
            return ExitSet.halted(outcome.effect, condition)
        return ExitSet.halted(outcome.effect)
    if isinstance(outcome, Complete):
        return ExitSet.completed(outcome.value)
    raise TypeError(
        f"sugar_outcome_to_exitset expects Complete|Incomplete, got {type(outcome).__name__}"
    )
