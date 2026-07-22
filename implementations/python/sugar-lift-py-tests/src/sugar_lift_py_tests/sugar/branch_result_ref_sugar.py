from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class BranchResultRefSugar(Sugar):
    slot: object
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultCoordinate,
        )
        from sugar_lift_py_tests.outcome import Complete

        return Complete(BranchResultCoordinate(self.slot, self.site))
