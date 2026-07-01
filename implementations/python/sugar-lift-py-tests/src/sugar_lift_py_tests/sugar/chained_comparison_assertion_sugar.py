from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    and_,
    eq,
    gt,
    gte,
    identity,
    lt,
    lte,
    ne,
)
from sugar_lift_py_tests.sugar.not_sugar import NotSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


_ORDER_FORMULAS: dict[str, Callable[[Term, Term], Formula]] = {
    "Eq": eq,
    "NotEq": ne,
    "Lt": lt,
    "LtE": lte,
    "Gt": gt,
    "GtE": gte,
}
_IDENTITY_OPERATORS = {"Is", "IsNot"}
_SUPPORTED_OPERATORS = set(_ORDER_FORMULAS) | _IDENTITY_OPERATORS


@dataclass(frozen=True)
class ChainedComparisonAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.chained-comparison-assertion-sugar"

    operators: tuple[str, ...]
    operands: tuple[Term, ...]

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        operators = test.compare_ops()
        comparators = test.compare_comparators()
        if len(operators) <= 1 or len(operators) != len(comparators):
            return False
        if any(operator not in _SUPPORTED_OPERATORS for operator in operators):
            return False
        return all(
            can_symbolic_term(operand)
            for operand in [test.compare_left(), *comparators]
        )

    @classmethod
    def build(cls, site, ctx) -> "ChainedComparisonAssertionSugar":
        test = site.assert_test()
        import_aliases = getattr(ctx, "import_aliases", {}) or {}
        from_imports = getattr(ctx, "from_imports", {}) or {}
        name_resolver = getattr(ctx, "name_resolver", {}) or {}
        external_bridge_sink = getattr(ctx, "external_bridge_sink", None)
        return cls(
            operators=tuple(test.compare_ops()),
            operands=tuple(
                symbolic_term(
                    operand,
                    owner="chained comparison assertion",
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for operand in [test.compare_left(), *test.compare_comparators()]
            ),
        )

    def assertion_formula(self) -> Formula:
        formulas = [
            _operator_formula(operator, left, right)
            for operator, left, right in zip(
                self.operators, self.operands, self.operands[1:]
            )
        ]
        return and_(formulas)

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()


def _operator_formula(operator: str, left: Term, right: Term) -> Formula:
    if operator in _ORDER_FORMULAS:
        return _ORDER_FORMULAS[operator](left, right)
    formula = identity(left, right)
    if operator == "Is":
        return formula
    if operator == "IsNot":
        return NotSugar().apply(formula)
    raise TypeError(
        f"write more Sugar for chained comparison operator `{operator}`: "
        "add ProofIR lowering"
    )
