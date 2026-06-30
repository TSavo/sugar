from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome

PrimitiveValue = int | str


@dataclass(frozen=True)
class PrimitiveLiteralSugar:
    value: PrimitiveValue

    @classmethod
    def from_site(cls, site) -> "PrimitiveLiteralSugar | None":
        if site.observed != "PrimitiveLiteral":
            return None
        value = site.literal_value()
        if not isinstance(value, (int, str)):
            return None
        return cls(value)

    def desugar(self) -> Outcome:
        if isinstance(self.value, int):
            return Complete(TermValue(self.value))
        if isinstance(self.value, str):
            return Complete(StringValue(self.value))
        raise TypeError(
            f"write more Floor for PrimitiveLiteralSugar value `{type(self.value).__name__}`"
        )


def _owns(site) -> bool:
    return PrimitiveLiteralSugar.from_site(site) is not None


def _build(site, _ctx) -> PrimitiveLiteralSugar:
    sugar = PrimitiveLiteralSugar.from_site(site)
    if sugar is None:
        raise TypeError("PrimitiveLiteralSugar claim built a non-primitive literal")
    return sugar


PRIMITIVE_LITERAL_CLAIM = SugarClaim(
    name="PrimitiveLiteralSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
