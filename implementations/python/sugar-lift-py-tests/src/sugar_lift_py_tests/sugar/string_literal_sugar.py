from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class StringLiteralSugar:
    value: str

    @classmethod
    def from_site(cls, site, _ctx=None) -> "StringLiteralSugar | None":
        if site.observed != "PrimitiveLiteral":
            return None
        value = site.literal_value()
        if not isinstance(value, str):
            return None
        return cls(value)

    def desugar(self) -> Outcome:
        return Complete(StringValue(self.value))
