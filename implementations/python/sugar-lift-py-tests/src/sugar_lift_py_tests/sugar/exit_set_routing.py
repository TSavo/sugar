"""Shared ExitSet helpers for Try and With contract routing.

A boundary hands back the ExitSet it routed. No completed record holds a halt
(#7826), so nothing here promotes a halt out of a record, and nothing projects
an ExitSet back onto a linear block view.
"""

from __future__ import annotations


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
    if isinstance(outcome, ExitSet):
        # A call that may complete or raise (a C call, an unprojected source
        # call) is already its own guarded faces; keep every one.
        return outcome
    raise TypeError(
        f"sugar_outcome_to_exitset expects Complete|Incomplete, got {type(outcome).__name__}"
    )
