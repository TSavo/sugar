from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class AttributeLookupOperation:
    name: str
    owner: str = "AttributeSugar"
    blame: str = "<unknown>"

    def attribute_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        for field in reversed(receiver.fields):
            if field.name == self.name:
                return Complete(field.value)
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver.class_name}.{self.name}",
            requested="constructor-bound field",
            fix=f"bind `self.{self.name}` in `{receiver.class_name}.__init__` or add the floor that owns this attribute",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="constructor-bound field",
                status="floor-gap",
                observed=info.observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
