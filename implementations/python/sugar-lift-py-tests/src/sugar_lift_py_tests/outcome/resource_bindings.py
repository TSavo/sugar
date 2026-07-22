"""Explicit record testimony for manager once-eval and enter-result auth.

Same posture as EffectBinding: coordinates are pure; authentication is
InvValue facts on the record — not ambient tables, not floor-side sealing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagerBinding:
    """Slot M is the once-evaluated manager expression result."""

    slot_id: str
    manager_value: object  # FloorValue

    def to_facts(self, site=None) -> tuple:
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import atomic, eq, str_const

        slot = str_const(self.slot_id)
        term = self.manager_value.to_term(owner="ManagerBinding")
        return (
            InvValue(
                eq(atomic("manager_slot_value", [slot]), term),
                site=site,
            ),
        )


@dataclass(frozen=True)
class EnterResultBinding:
    """Slot E is authenticated by the completed ``__enter__`` result."""

    slot_id: str
    enter_value: object  # FloorValue

    def to_facts(self, site=None) -> tuple:
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import atomic, eq, str_const

        slot = str_const(self.slot_id)
        term = self.enter_value.to_term(owner="EnterResultBinding")
        return (
            InvValue(
                eq(atomic("enter_result_value", [slot]), term),
                site=site,
            ),
        )


def prepend_facts_to_exitset(exits, facts: tuple):
    """Attach binding facts to every completed exit's entry list."""
    from dataclasses import replace

    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if not facts:
        return exits
    out = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            out.append(exit_)
            continue
        value = exit_.value
        if isinstance(value, _ReducedBlock):
            out.append(
                Completed(
                    exit_.guard,
                    replace(value, entries=(*facts, *value.entries)),
                )
            )
        else:
            out.append(
                Completed(
                    exit_.guard,
                    _ReducedBlock(
                        entries=(*facts,),
                        can_fall_through=True,
                        fall_through=(),
                    ),
                )
            )
    return ExitSet(tuple(out)).normalize()
