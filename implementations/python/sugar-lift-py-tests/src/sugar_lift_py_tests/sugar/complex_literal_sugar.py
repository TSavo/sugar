from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class ComplexLiteralSugar(Sugar, role=SugarRole.TERM):
    """A complex literal using the established ``py.complex(real, imag)`` term."""

    value: complex
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Constant" and type(site.literal_value()) is complex

    @classmethod
    def new(cls, site, ctx) -> "ComplexLiteralSugar":
        del ctx
        return cls(value=site.literal_value(), site=site)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="complex_literal_return",
            owner_sugar="ComplexLiteralSugar",
            body="2j",
            truthful="2j",
            lying="3j",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, real_lit

        def part(value: float):
            return real_lit(format(Decimal(str(value)), "f"))

        return Complete(
            SymbolicValue(
                ctor("py.complex", [part(self.value.real), part(self.value.imag)])
            )
        )
