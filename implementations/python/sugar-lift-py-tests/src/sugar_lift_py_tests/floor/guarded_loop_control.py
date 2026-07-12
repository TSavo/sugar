from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedLoopControl(FloorValue):
    guards: tuple
    action: str
    locus: str

    def guarded(self, formula):
        return GuardedLoopControl((formula, *self.guards), self.action, self.locus)

    def post_contribution(self):
        from .loop_control_value import _loop_control_formula

        return (_loop_control_formula(self.action, self.locus, self.guards),)
