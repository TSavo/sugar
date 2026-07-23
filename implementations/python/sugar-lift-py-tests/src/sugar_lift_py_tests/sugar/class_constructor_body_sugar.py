from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ClassConstructorBodySugar(Sugar):
    definition: Sugar
    formal_coordinates: tuple[object, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ObjectValue",
            reason="a class call projects its ordinary definition and initializer",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if ctx is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="ClassConstructorBodySugar.desugar",
                observed="missing source-call binding frame",
                requested="coordinate-bound class constructor actuals",
                fix="reduce the class call through its SourceVisibleCallFrameV1",
            )
        actuals = tuple(
            ctx.value_for_binding_coordinate(item.cid)
            for item in self.formal_coordinates
        )
        return self.definition.desugar(ctx).and_then(
            lambda value: Complete(value.construct_receiver_state(actuals))
        )
