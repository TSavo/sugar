"""`(name := value)` — walrus expression sugar."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NamedExprSugar(ConstructedTermSugar):
    """A walrus: binds ``name`` and presents ``value``.

    Tree substitute threads the binding into the enclosing block. At the
    meaning layer the expression evaluates to ``NamedExpressionValue``.

    Enrolled as ``ConstructedTermSugar`` so Compare/Eq parents may carry the
    walrus as an operand through the typed term surface (no spelling side-door).
    """

    name: str
    value: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.value, owner="NamedExprSugar.value")

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

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:named-expr-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.name),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )

        return self.value.desugar(ctx).and_then(
            lambda assigned: Complete(NamedExpressionValue(self.name, assigned))
        )
