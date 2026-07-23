from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class BindingCoordinateRefSugar(Sugar):
    coordinate: object
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="FloorValue",
            reason="a formal projection reuses its authenticated constructed actual",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if ctx is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="BindingCoordinateRefSugar.desugar",
                observed="missing source-call binding frame",
                requested="the exact constructed actual for this BindingCoordinateV1",
                fix="reduce the source body through its authenticated call frame",
            )
        return Complete(ctx.value_for_binding_coordinate(self.coordinate.cid))
