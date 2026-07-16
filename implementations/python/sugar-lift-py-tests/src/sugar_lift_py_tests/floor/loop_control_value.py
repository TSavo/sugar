from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class LoopControlValue(FloorValue):
    non_fol_support = True

    action: str
    locus: str

    def follow_rest(self):
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.halt(keeps_rest=True)

    def guarded(self, formula):
        from .guarded_loop_control import GuardedLoopControl

        return GuardedLoopControl((formula,), self.action, self.locus)

    def post_contribution(self):
        return ()
