from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class LoopControlValue(FloorValue):
    action: str
    locus: str

    def follow_rest(self, rest, reduce):
        del reduce
        return rest

    def guarded(self, formula):
        from .guarded_loop_control import GuardedLoopControl

        return GuardedLoopControl((formula,), self.action, self.locus)

    def post_contribution(self):
        return ()
