"""`(name := value)` — walrus expression sugar."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NamedExprSugar(Sugar):
    """A walrus: binds ``name`` (spent by substitute) and presents ``value``.

    The tree threads the binding into the enclosing block via
    ``NamedExpr.substitution_binding``. At the meaning layer the expression
    evaluates to the assigned value wrapped as ``NamedExpressionValue``.
    """

    name: str
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(xs):\n    if (n := len(xs)) > 0:\n        return n\n    return 0\n\n"
        )
        return _call_pair(
            name="named_expr_if",
            owner_sugar="NamedExprSugar",
            truthful=prefix + "def test_a():\n    assert A([1, 2]) == 2\n",
            lying=prefix + "def test_a():\n    assert A([1, 2]) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )

        return self.value.desugar(ctx).and_then(
            lambda assigned: Complete(NamedExpressionValue(self.name, assigned))
        )
