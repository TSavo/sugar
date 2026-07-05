from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.ir import Formula, and_, or_
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import boolop_assertion_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BoolOpAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.boolop-assertion-sugar"

    operator: str
    values: tuple[SugarBody, ...]

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        return test.observed == "BoolOp" and test.boolop_op_kind() in {"and", "or"}

    @classmethod
    def witnesses(cls):
        return boolop_assertion_witness()

    @classmethod
    def build(cls, site, ctx) -> "BoolOpAssertionSugar":
        test = site.assert_test()
        return cls(
            operator=test.boolop_op_kind(),
            values=tuple(
                _assertion_child(site.assert_with_test(value), ctx)
                for value in test.boolop_values()
            ),
        )

    def desugar(self, ctx) -> Formula | Incomplete:
        formulas: list[Formula] = []
        for value in self.values:
            formula = value.reduce(ctx)
            if isinstance(formula, Incomplete):
                return formula
            formulas.append(formula)
        if self.operator == "and":
            return and_(formulas)
        if self.operator == "or":
            return or_(formulas)
        raise TypeError(
            f"write more Sugar for BoolOpAssertionSugar `{self.operator}`: "
            "add assertion connective lowering"
        )


def _assertion_child(site, ctx) -> SugarBody:
    if not ctx.catalog.candidates_for(SugarRole.ASSERTION, site):
        return SugarBody(
            _RuntimeAssertionEffect(
                owner="BoolOpAssertionSugar",
                observed=site.assert_test().observed,
                requested=SugarRole.ASSERTION.value,
                replacement=f"create {site.suggested_sugar_module}",
                blame=site.blame,
            ),
            SugarRole.ASSERTION,
        )
    return ctx.build_body(site, SugarRole.ASSERTION)


@dataclass(frozen=True)
class _RuntimeAssertionEffect:
    owner: str
    observed: str
    requested: str
    replacement: str
    blame: str

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "assertion runtime boundary: "
                f"{self.owner} child {self.observed} cannot be reduced to a static "
                "assertion formula; Python evaluates this assertion branch at "
                "runtime. "
                f"replacement={self.requested}; fix={self.replacement}; "
                f"blame={self.blame}"
            )
        )
