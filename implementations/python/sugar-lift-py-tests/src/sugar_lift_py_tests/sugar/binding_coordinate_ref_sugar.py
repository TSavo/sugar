from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class BindingCoordinateRefSugar(ConstructedTermSugar):
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
        if ctx is not None and hasattr(ctx, "temporal"):
            value = ctx.temporal.value_if_bound(self.coordinate.cid)
            if value is not None:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(value)
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.site,
            owner="BindingCoordinateRefSugar.desugar",
            observed="unspecialized source-call formal",
            requested="runtime BindingEntryV1 substitution before Sugar construction",
            fix="bind the exact typed actual Node through SourceVisibleCallFrameV1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:binding-coordinate-reference",
            (self.occurrence_term(owner=owner), str_const(self.coordinate.cid)),
            symbol_kind="coordinate",
        )
