from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedRaise(FloorValue):
    """A raise exit reached only under a guard.

    `except` routes this exactly like an unguarded `RaiseValue`, preserving the
    guards while currying the handler body.
    """

    guards: tuple
    effect: RaiseEffect
    scope: object = None

    def guarded(self, formula):
        return GuardedRaise(
            guards=(formula, *self.guards),
            effect=self.effect,
            scope=self.scope,
        )
