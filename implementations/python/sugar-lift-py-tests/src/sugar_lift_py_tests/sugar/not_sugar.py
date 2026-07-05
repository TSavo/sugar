from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.ir import Formula, atomic, ctor, eq, gt, gte, lt, lte, ne, not_
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar.witness_examples import not_assertion_witness
from sugar_lift_py_tests.sugar_body import SugarBody

_OPERATOR_FORMULAS = {
    "Eq": eq,
    "NotEq": ne,
    "Lt": lt,
    "LtE": lte,
    "Gt": gt,
    "GtE": gte,
}
_NOT_BINOP_SYMBOL = {
    "BitAnd": "&",
    "BitOr": "|",
    "BitXor": "^",
    "LShift": "<<",
    "RShift": ">>",
}


@dataclass(frozen=True)
class NotSugar(Sugar, role=SugarRole.ASSERTION):
    """A polarity marker.

    Python has both shapes:
      * `assert not <expr>` is a normal wrapper: build the child assertion body,
        then negate whatever it lowers to.
      * `x is not y` is not an outer `not` expression around `is`; it is a
        single comparison operator. In that shape this class is only a marker:
        the relation sugar owns the relation and calls `apply`.
    """

    source_role = "python.not-sugar"

    body: SugarBody | None = None
    formula: Formula | None = None
    runtime_reason: str | None = None
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        return test.observed == "UnaryOp" and test.operator_kind() == "Not"

    @classmethod
    def build(cls, site, ctx) -> "NotSugar":
        test = site.assert_test()
        operand_assert = site.assert_with_test(test.unaryop_operand())
        formula = _symbolic_assertion_formula(operand_assert, ctx)
        if formula is not None and _prefer_symbolic_formula(operand_assert):
            return cls(formula=formula)
        if not ctx.catalog.candidates_for(SugarRole.ASSERTION, operand_assert):
            return cls(
                runtime_reason=(
                    f"NotSugar child {operand_assert.assert_test().observed} "
                    "cannot be reduced to a static assertion formula; Python "
                    "evaluates this negated assertion at runtime. "
                    f"replacement={SugarRole.ASSERTION.value}; "
                    f"fix=create {operand_assert.suggested_sugar_module}"
                ),
                blame=site.blame,
            )
        return cls(body=ctx.build_body(operand_assert, SugarRole.ASSERTION))

    @classmethod
    def witnesses(cls):
        return not_assertion_witness()

    def apply(self, formula: Formula) -> Formula:
        return not_(formula)

    def _build(self, ctx) -> Formula | Incomplete:
        if self.runtime_reason is not None:
            return Incomplete(
                RuntimeEffect(
                    "assertion runtime boundary: "
                    f"{self.runtime_reason}; blame={self.blame}"
                )
            )
        if self.body is not None:
            formula = self.body.reduce(ctx)
            if isinstance(formula, Incomplete):
                return formula
            return self.apply(formula)
        if self.formula is not None:
            return self.apply(self.formula)
        raise TypeError("NotSugar polarity marker has no assertion body to desugar")


def _symbolic_assertion_formula(site, ctx) -> Formula | None:
    test = site.assert_test()
    if test.observed == "Compare":
        if len(test.compare_ops()) != 1 or len(test.compare_comparators()) != 1:
            return None
        operator = test.compare_ops()[0]
        builder = _OPERATOR_FORMULAS.get(operator)
        if builder is None:
            return None
        left = test.compare_left()
        right = test.compare_comparators()[0]
        if not (can_symbolic_term(left) and can_symbolic_term(right)):
            return None
        return builder(
            symbolic_term(
                left,
                owner="not assertion comparison left",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            symbolic_term(
                right,
                owner="not assertion comparison right",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
        )
    if not _can_not_symbolic_term(test):
        return None
    return atomic(
        "py.truthy",
        [
            _not_symbolic_term(
                test,
                owner="not assertion truthy operand",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            )
        ],
    )


def _prefer_symbolic_formula(site) -> bool:
    test = site.assert_test()
    if test.observed == "Compare":
        return any(child.observed == "Call" for child in test.walk())
    return test.observed == "BinOp" and test.operator_kind() in {
        "BitAnd",
        "BitOr",
        "BitXor",
        "LShift",
        "RShift",
    }


def _can_not_symbolic_term(site) -> bool:
    if site.observed == "BinOp" and site.operator_kind() in _NOT_BINOP_SYMBOL:
        return _can_not_symbolic_term(site.binop_left()) and _can_not_symbolic_term(
            site.binop_right()
        )
    return can_symbolic_term(site)


def _not_symbolic_term(
    site,
    *,
    owner: str,
    import_aliases,
    from_imports,
    name_resolver,
    external_bridge_sink,
):
    if site.observed == "BinOp" and site.operator_kind() in _NOT_BINOP_SYMBOL:
        return ctor(
            _NOT_BINOP_SYMBOL[site.operator_kind()],
            [
                _not_symbolic_term(
                    site.binop_left(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
                _not_symbolic_term(
                    site.binop_right(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
            ],
        )
    return symbolic_term(
        site,
        owner=owner,
        import_aliases=import_aliases,
        from_imports=from_imports,
        name_resolver=name_resolver,
        external_bridge_sink=external_bridge_sink,
    )
