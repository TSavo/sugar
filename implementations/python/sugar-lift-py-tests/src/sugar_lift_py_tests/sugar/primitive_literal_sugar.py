from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar

PrimitiveValue = int | float | str


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
    def from_site(cls, site) -> "PrimitiveLiteralSugar | None":
        if site.observed != "PrimitiveLiteral":
            return None
        value = site.literal_value()
        if not isinstance(value, (int, float, str)):
            return None
        return cls(value)

    def desugar(self) -> Outcome:
        if isinstance(self.value, (int, float)):
            return Complete(TermValue(self.value))
        if isinstance(self.value, str):
            return Complete(StringValue(self.value))
        raise TypeError(
            f"write more Floor for PrimitiveLiteralSugar value `{type(self.value).__name__}`"
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
PRIMITIVE_LITERAL_CLAIM = next(c for c in _rc() if c.name == "PrimitiveLiteralSugar")
