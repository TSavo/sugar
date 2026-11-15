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
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here

        # An ``if``'s slot is read as the live loop item running now decides
        # it (``branch_slot_here``), never as one decision every item shares.
        table = getattr(ctx, "ground_branch_results", None)
        if isinstance(table, dict):
            from sugar_lift_py_tests.sugar.call_site_sugar import branch_result_read

            bound = branch_result_read(
                table, branch_slot_here(self.slot, table).slot_id
            )
            if bound is not None:
                return ExitSet.completed(bound)
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultCoordinate,
            undecided_slot_debt,
        )

        # No decision and no reading on this path: the slot's coordinate is
        # a flag no input decides, so the read owes the undecided member and
        # every arm the phi selects by it owes it too (``and_then``), never a
        # value the solver may pick by choosing the flag (#7757).
        return ExitSet.completed(
            BranchResultCoordinate(branch_slot_here(self.slot), self.site),
            owed=undecided_slot_debt(self.site),
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:branch-result-reference",
            (self.occurrence_term(owner=owner), str_const(self.slot.slot_id)),
            symbol_kind="coordinate",
        )
