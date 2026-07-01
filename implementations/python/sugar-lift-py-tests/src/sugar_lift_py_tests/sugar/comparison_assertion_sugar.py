from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, eq, gt, gte, lt, lte, ne
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term

_OPERATOR_FORMULAS: dict[str, Callable[[Term, Term], Formula]] = {
    "Eq": eq,
    "NotEq": ne,
    "Lt": lt,
    "LtE": lte,
    "Gt": gt,
    "GtE": gte,
}


@dataclass(frozen=True)
class ComparisonAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.comparison-assertion-sugar"

    operator: str
    left: Term
    right: Term

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        if len(test.compare_ops()) != 1 or len(test.compare_comparators()) != 1:
            return False
        operator = test.compare_ops()[0]
        if operator not in _OPERATOR_FORMULAS:
            return False
        left = test.compare_left()
        right = test.compare_comparators()[0]
        if operator == "Eq":
            if left.observed in {"Attribute", "Subscript"}:
                return False
            if _contains_call(left) or _contains_call(right):
                return False
        return can_symbolic_term(left) and can_symbolic_term(right)

    @classmethod
    def build(cls, site, ctx) -> "ComparisonAssertionSugar":
        test = site.assert_test()
        import_aliases = getattr(ctx, "import_aliases", {}) or {}
        from_imports = getattr(ctx, "from_imports", {}) or {}
        name_resolver = getattr(ctx, "name_resolver", {}) or {}
        external_bridge_sink = getattr(ctx, "external_bridge_sink", None)
        return cls(
            operator=test.compare_ops()[0],
            left=symbolic_term(
                test.compare_left(),
                owner="comparison assertion left",
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            ),
            right=symbolic_term(
                test.compare_comparators()[0],
                owner="comparison assertion right",
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            ),
        )

    def assertion_formula(self) -> Formula:
        return _OPERATOR_FORMULAS[self.operator](self.left, self.right)

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()


def _contains_call(site) -> bool:
    if site.observed == "Call":
        return True
    return any(child.observed == "Call" for child in site.walk())
