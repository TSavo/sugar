from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class BoolOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BoolOp"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "boolean expressions in value position short-circuit and return "
                "runtime operand values rather than a pure bool fact"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "BoolOpSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("BoolOpSugar claim built a non-boolop expression")
        return cls(operator=site.boolop_op_kind(), blame=site.blame)

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "boolean expression runtime boundary: Python short-circuits "
                f"`{self.operator}` and returns one of the original operand "
                "values, not a standalone boolean floor; keep as typed red until "
                f"truthiness/value-flow floors own this shape. blame={self.blame}"
            )
        )
