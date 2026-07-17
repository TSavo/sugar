from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .floor_value import FloorValue
from .exception_cause_value import ExceptionCauseValue


@dataclass(frozen=True)
class GuardedRaise(FloorValue):
    """A raise exit reached only under a guard.

    `except` routes this exactly like an unguarded `RaiseValue`, preserving the
    guards while currying the handler body.
    """

    guards: tuple
    effect: RaiseEffect
    scope: object = None
    cause: ExceptionCauseValue | None = None

    def guarded(self, formula):
        return GuardedRaise(
            guards=(formula, *self.guards),
            effect=self.effect,
            scope=self.scope,
            cause=self.cause,
        )

    def post_contribution(self):
        from sugar_lift_py_tests.floor.raise_value import _exceptional_exit_formula

        return (_exceptional_exit_formula(self.effect, self.guards),)
