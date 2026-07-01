from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class AttributeSugar(Sugar, role=SugarRole.TERM):
    term: Term

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Attribute" and can_symbolic_term(site)

    @classmethod
    def build(cls, site, ctx) -> "AttributeSugar":
        del ctx
        return cls(term=symbolic_term(site, owner="attribute sugar"))

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Complete(SymbolicValue(self.term))
