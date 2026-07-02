from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import AttributeDeleteOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    name: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Delete":
            return False
        targets = site.delete_targets()
        return len(targets) == 1 and targets[0].observed == "Attribute"

    @classmethod
    def build(cls, site, ctx) -> "AttributeDeleteSugar":
        target = site.delete_targets()[0]
        return cls(
            receiver=ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            name=target.attr_name(),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(receiver_outcome, owner="AttributeDeleteSugar receiver")
        return perform_operation(
            owner="AttributeDeleteSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="attribute_delete_with",
            operation=AttributeDeleteOperation(
                name=self.name,
                owner="AttributeDeleteSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
