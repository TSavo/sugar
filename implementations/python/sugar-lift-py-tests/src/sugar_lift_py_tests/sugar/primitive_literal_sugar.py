from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoolValue, StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import primitive_literal_return_witness

PrimitiveValue = bool | int | float | str | None


@dataclass(frozen=True)
class PrimitiveLiteralSugar(Sugar, role=SugarRole.TERM):
    value: PrimitiveValue

    @classmethod
    def owns(cls, site) -> bool:
        return cls.from_site(site) is not None

    @classmethod
    def build(cls, site, ctx) -> "PrimitiveLiteralSugar":
        sugar = cls.from_site(site)
        if sugar is None:
            raise TypeError("PrimitiveLiteralSugar claim built a non-primitive literal")
        return sugar

    @classmethod
    def witnesses(cls):
        return primitive_literal_return_witness()

    @classmethod
    def from_site(cls, site) -> "PrimitiveLiteralSugar | None":
        if site.observed != "PrimitiveLiteral":
            return None
        value = site.literal_value()
        if value is not None and not isinstance(value, (int, float, str)):
            return None
        return cls(value)

    def _build(self) -> Outcome:
        # Collapsed numeric type: int AND float are the same Number value (Int embeds in
        # Real losslessly), so 3 and 3.0 share one TermValue and 3.0 == 3 is reflexive.
        if isinstance(self.value, bool):
            return Complete(BoolValue(self.value))
        if isinstance(self.value, (int, float)):
            return Complete(TermValue(self.value))
        if isinstance(self.value, str):
            return Complete(StringValue(self.value))
        if self.value is None:
            return Complete(SymbolicValue(ctor("None", [])))
        raise TypeError(
            f"write more Floor for PrimitiveLiteralSugar value `{type(self.value).__name__}`"
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

PRIMITIVE_LITERAL_CLAIM = next(c for c in _rc() if c.name == "PrimitiveLiteralSugar")
