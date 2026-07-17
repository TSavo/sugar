from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionalExitValue(FloorValue):
    """A reduced raise projected into a return-selection branch.

    This is control-flow testimony, not a Python exception instance and not a
    RuntimeEffect. Its term is the same source-cited exceptional-exit
    coordinate emitted by ``RaiseValue`` and ``GuardedRaise`` posts.
    """

    effect: RaiseEffect

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.floor.raise_value import _exceptional_exit_term

        return _exceptional_exit_term(self.effect)
