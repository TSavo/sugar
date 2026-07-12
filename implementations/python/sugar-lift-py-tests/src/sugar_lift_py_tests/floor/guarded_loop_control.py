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
        return ()
