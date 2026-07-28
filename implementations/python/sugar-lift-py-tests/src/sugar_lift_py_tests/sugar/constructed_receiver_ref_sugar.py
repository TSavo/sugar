from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ConstructedReceiverRefSugar(Sugar):
    class_name: str
    binding_coordinate_cid: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ObjectValue",
            reason="a class call constructs its receiver from the authenticated class definition",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if ctx is not None:
            receiver = ctx.temporal.value_if_bound(self.binding_coordinate_cid)
            if isinstance(receiver, ObjectValue):
                return Complete(receiver)
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ConstructedReceiverRefSugar",
            blame=str(self.site),
            observed=self.binding_coordinate_cid,
            requested="the class-construction receiver binding",
            fix="bind the constructed receiver before reducing its initializer",
        )
