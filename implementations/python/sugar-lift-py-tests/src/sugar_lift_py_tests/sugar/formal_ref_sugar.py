from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class FormalRefSugar(Sugar):
    coordinate: FormalParameterCoordinateV1
    site: object = field(compare=False)

    @property
    def name(self) -> str:
        return self.coordinate.declared_name

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar.witnesses()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(
                make_var(self.coordinate.declared_name),
                formal_coordinate=self.coordinate,
            )
        )
