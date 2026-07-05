from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class ForSugar(Sugar, role=SugarRole.STATEMENT):
    blame: str
    target_observed: str
    has_else: bool

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "For"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "for loops need iterator-state and body-effect floors before they "
                "can carry a standalone solver verdict"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "ForSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("ForSugar claim built a non-for statement")
        return cls(
            blame=site.blame,
            target_observed=site.for_target_observed(),
            has_else=site.for_orelse_count() != 0,
        )

    def desugar(self, ctx) -> Outcome:
        del ctx
        else_note = " with else/fallthrough" if self.has_else else ""
        return Incomplete(
            RuntimeEffect(
                "for loop runtime boundary: Python evaluates iterator protocol, "
                f"target binding `{self.target_observed}`, loop body effects"
                f"{else_note}, and fallthrough at runtime; keep as typed red "
                "until iterator/body floors own this shape. "
                f"blame={self.blame}"
            )
        )
