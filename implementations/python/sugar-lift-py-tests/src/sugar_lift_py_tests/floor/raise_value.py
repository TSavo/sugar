from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .floor_value import FloorValue


@dataclass(frozen=True)
class RaiseValue(FloorValue):
    """A Python raise exit carried by a block frontier.

    This is control-flow data, not an `Incomplete`: a `TrySugar` may route it through
    a matching handler before universe lowering decides what residual effects remain.
    """

    effect: RaiseEffect
    scope: object = None

    def follow_rest(self, rest, reduce):
        # Code after an unguarded raise never runs and is not part of the
        # block record (unreachable). Drop it — same posture as a hard exit.
        del rest, reduce
        return ()

    def guarded(self, formula):
        from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise

        return GuardedRaise(guards=(formula,), effect=self.effect, scope=self.scope)
