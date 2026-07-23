from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class PlaceAssignSugar(Sugar):
    receiver: Sugar
    selector_kind: str
    selector: object
    value: Sugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="PlaceAssignValue",
            reason="authenticated place store mirrors the Python reference assignment",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.place_assign_value import PlaceAssignValue

        def with_receiver(receiver):
            def with_value(value):
                if self.selector_kind == "attribute":
                    selector = self.selector
                elif self.selector_kind == "subscript":
                    return self.selector.desugar(ctx).and_then(
                        lambda selector: Complete(
                            PlaceAssignValue(
                                receiver, "subscript", selector, value
                            )
                        )
                    )
                else:
                    raise ValueError("typed place selector mismatch")
                return Complete(
                    PlaceAssignValue(receiver, "attribute", selector, value)
                )

            return self.value.desugar(ctx).and_then(with_value)

        return self.receiver.desugar(ctx).and_then(with_receiver)
