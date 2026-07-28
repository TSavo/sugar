from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class FormalRefSugar(ConstructedTermSugar):
    coordinate: FormalParameterCoordinateV1
    site: object = field(compare=False)

    @property
    def name(self) -> str:
        return self.coordinate.declared_name

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar.witnesses()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:formal-reference-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.coordinate.coordinate_cid),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(
                make_var(self.coordinate.declared_name),
                formal_coordinate=self.coordinate,
            )
        )
