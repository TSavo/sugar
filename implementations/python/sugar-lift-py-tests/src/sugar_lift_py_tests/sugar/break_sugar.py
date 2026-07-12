from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import LoopControlValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class BreakSugar(Sugar, role=SugarRole.STATEMENT):
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Break" and site.has_enclosing_loop()

    @classmethod
    def new(cls, site, ctx) -> "BreakSugar":
        del ctx
        return cls(site)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="LoopControlValue",
            reason="break cites the enclosing loop exit instead of a function verdict",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(LoopControlValue("break", str(self.site)))

    def walk_children(self):
        return ()
