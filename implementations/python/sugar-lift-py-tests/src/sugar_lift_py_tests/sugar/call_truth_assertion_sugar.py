from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, atomic
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class CallTruthAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.call-truth-assertion-sugar"

    call: Term

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Call":
            return False
        if test.call_target_name() == "isinstance":
            return False
        return can_symbolic_term(test)

    @classmethod
    def build(cls, site, ctx) -> "CallTruthAssertionSugar":
        del ctx
        return cls(call=symbolic_term(site.assert_test(), owner="call truth assertion"))

    def assertion_formula(self) -> Formula:
        return atomic("py.truthy", [self.call])

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()
