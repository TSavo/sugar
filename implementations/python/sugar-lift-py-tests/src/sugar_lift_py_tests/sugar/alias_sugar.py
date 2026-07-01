from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ImportAliasValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AliasSugar(Sugar, role=SugarRole.TERM):
    name: str
    bound_name: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "alias"

    @classmethod
    def build(cls, site, ctx) -> "AliasSugar":
        del ctx
        if site.observed != "alias":
            raise TypeError("AliasSugar claim built a non-alias")
        return cls(name=site.alias_name(), bound_name=site.alias_bound_name())

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Complete(ImportAliasValue(name=self.name, bound_name=self.bound_name))
