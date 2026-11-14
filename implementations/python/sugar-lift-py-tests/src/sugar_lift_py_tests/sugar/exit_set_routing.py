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
    """The ExitSet a tree-owned enter/exit method-coordinate sugar answered.

    A sugar answers an ``ExitSet`` already (#7825): a call that may complete
    or raise is its own guarded faces, and every one is kept. Anything else is
    refused by name.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(outcome, ExitSet):
        return outcome
    raise TypeError(
        f"sugar_outcome_to_exitset expects ExitSet, got {type(outcome).__name__}"
    )
