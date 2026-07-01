from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, atomic
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class TruthyAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.truthy-assertion-sugar"

    term: Term

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed in {"Call", "Compare", "UnaryOp"}:
            return False
        return can_symbolic_term(test)

    @classmethod
    def build(cls, site, ctx) -> "TruthyAssertionSugar":
        return cls(
            term=symbolic_term(
                site.assert_test(),
                owner="truthy assertion",
                import_aliases=getattr(ctx, "import_aliases", {}) or {},
                from_imports=getattr(ctx, "from_imports", {}) or {},
                name_resolver=getattr(ctx, "name_resolver", {}) or {},
                external_bridge_sink=getattr(ctx, "external_bridge_sink", None),
            )
        )

    def assertion_formula(self) -> Formula:
        return atomic("py.truthy", [self.term])

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()
