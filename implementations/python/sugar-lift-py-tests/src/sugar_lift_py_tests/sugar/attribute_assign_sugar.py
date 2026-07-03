from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import AttributeMutationOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeAssignSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    name: str
    value: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) == 1 and targets[0].observed == "Attribute"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "attribute mutation is stateful support until object-field "
                "updates carry a solver verdict"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "AttributeAssignSugar":
        target = site.assign_targets()[0]
        return cls(
            receiver=ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            name=target.attr_name(),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        value_outcome = self.value.reduce(ctx)
        if isinstance(value_outcome, Incomplete):
            return value_outcome
        receiver = complete_value(
            receiver_outcome, owner="AttributeAssignSugar receiver"
        )
        value = complete_value(value_outcome, owner="AttributeAssignSugar value")
        return perform_operation(
            owner="AttributeAssignSugar",
            blame=self.blame,
            receiver=receiver,
            operation=AttributeMutationOperation(
                name=self.name,
                value=value,
                owner="AttributeAssignSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
