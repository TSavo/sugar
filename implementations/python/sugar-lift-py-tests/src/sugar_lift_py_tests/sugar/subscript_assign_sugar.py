from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.operations import SetItemOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptAssignSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    index: SugarBody
    value: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("SubscriptAssignSugar receiver must be factory-built")
        if not isinstance(self.index, SugarBody):
            raise TypeError("SubscriptAssignSugar index must be factory-built")
        if not isinstance(self.value, SugarBody):
            raise TypeError("SubscriptAssignSugar value must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) == 1 and targets[0].observed == "Subscript"

    @classmethod
    def build(cls, site, ctx) -> "SubscriptAssignSugar":
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed != "Subscript":
            raise TypeError(
                "SubscriptAssignSugar claim built a non-subscript assignment"
            )
        target = targets[0]
        return cls(
            receiver=ctx.build_body(target.subscript_receiver(), SugarRole.TERM),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        index_outcome = self.index.reduce(ctx)
        if isinstance(index_outcome, Incomplete):
            return index_outcome
        value_outcome = self.value.reduce(ctx)
        if isinstance(value_outcome, Incomplete):
            return value_outcome

        mutation = perform_operation(
            owner="SubscriptAssignSugar",
            blame=self.blame,
            receiver=complete_value(
                receiver_outcome, owner="SubscriptAssignSugar receiver"
            ),
            method_name="setitem_with",
            operation=SetItemOperation(
                index=complete_value(index_outcome, owner="SubscriptAssignSugar index"),
                value=complete_value(value_outcome, owner="SubscriptAssignSugar value"),
                owner="SubscriptAssignSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
        if isinstance(mutation, Incomplete):
            return mutation
        return Complete(SupportValue())
