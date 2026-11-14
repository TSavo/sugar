from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class BranchResultRefSugar(ConstructedTermSugar):
    slot: object
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import ExitSet

        table = getattr(ctx, "ground_branch_results", None)
        if isinstance(table, dict):
            bound = table.get(self.slot.slot_id)
            if bound is not None:
                return ExitSet.completed(bound)
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultCoordinate,
        )

        return ExitSet.completed(BranchResultCoordinate(self.slot, self.site))

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:branch-result-reference",
            (self.occurrence_term(owner=owner), str_const(self.slot.slot_id)),
            symbol_kind="coordinate",
        )
