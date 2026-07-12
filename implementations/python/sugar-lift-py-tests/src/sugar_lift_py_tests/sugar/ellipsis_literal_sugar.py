from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class EllipsisLiteralSugar(Sugar, role=SugarRole.TERM):
    """Python's Ellipsis singleton as its native ProofIR coordinate."""

    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Constant" and site.literal_value() is Ellipsis

    @classmethod
    def new(cls, site, ctx) -> "EllipsisLiteralSugar":
        del ctx
        return cls(site=site)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="ellipsis_literal_return",
            owner_sugar="EllipsisLiteralSugar",
            body="...",
            truthful="...",
            lying="None",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        return Complete(SymbolicValue(ctor("py.ellipsis", [])))
