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
        del ctx
        return Complete(
            ObjectValue(self.class_name, (), identity=self.binding_coordinate_cid)
        )
