from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class StarredSugar(Sugar, role=SugarRole.TERM):
    blame: str
    operand_observed: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Starred"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "starred expression expansion is runtime call/display support, "
                "not a standalone FOL claim"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "StarredSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("StarredSugar claim built a non-Starred")
        terms = site.terms()
        operand = terms[0].observed if terms else "<missing>"
        return cls(blame=site.blame, operand_observed=operand)

    def desugar(self, ctx) -> Outcome:
        del ctx
        return _runtime_expansion_effect(self.blame, self.operand_observed)


def _runtime_expansion_effect(blame: str, operand_observed: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "starred expression runtime boundary: "
            f"operand `{operand_observed}` must be iterated at runtime before "
            "call or display construction. Python evaluates this at runtime; "
            "keep as typed red until a narrower vendor-cited reduction owns "
            f"the shape. blame={blame}"
        )
    )
