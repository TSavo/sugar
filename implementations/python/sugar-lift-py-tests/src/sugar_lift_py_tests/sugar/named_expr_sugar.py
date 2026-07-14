from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import NamedExpressionValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NamedExprSugar(Sugar, role=SugarRole.TERM):
    """A walrus expression is its RHS plus an ordinary temporal name bind."""

    target_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "NamedExpr"

    @classmethod
    def new(cls, site, ctx) -> "NamedExprSugar":
        return cls(
            target_name=site.named_expr_target_name(),
            value=ctx.build_body(site.named_expr_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    return (seen := z)\n\n"
        return _call_pair(
            name="named_expr_binding_return",
            owner_sugar="NamedExprSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: Complete(NamedExpressionValue(self.target_name, value))
        )

    def walk_children(self):
        return (self.value,)
