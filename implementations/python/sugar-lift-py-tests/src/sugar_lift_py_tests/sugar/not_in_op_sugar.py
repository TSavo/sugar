from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NotInOpSugar(Sugar, role=SugarRole.TERM):
    """The ``not in`` operator: ``needle not in haystack``.

    Emits ``not(py.in(needle, haystack))`` as a PredicateValue. Companion to
    InOpSugar for message / membership checks.
    """

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["NotIn"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "NotInOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z not in (1, 2, 3):\n"
            "        return 0\n"
            "    return 1\n"
            "\n"
        )
        finite_domain = (
            "import pytest\n"
            "def identity(value):\n"
            "    return value\n"
            "\n"
            "@pytest.mark.parametrize('z, expected', [(1, 10), (2, 20), (3, 30)])\n"
            "def test_b(z, expected):\n"
            "    if z not in (1, 2, 3):\n"
            "        result = 0\n"
            "    elif z == 1:\n"
            "        result = 10\n"
            "    elif z == 2:\n"
            "        result = 20\n"
            "    elif z == 3:\n"
            "        result = 30\n"
        )
        return (
            _call_pair(
                name="not_in_return",
                owner_sugar="NotInOpSugar",
                truthful=prefix + "def test_a():\n    assert A(9) == 0\n",
                lying=prefix + "def test_a():\n    assert A(9) == 1\n",
            ),
            _call_pair(
                name="not_in_finite_domain_continuation",
                owner_sugar="NotInOpSugar",
                truthful=finite_domain + "    assert identity(result) == expected\n",
                lying=finite_domain + "    assert identity(result) == expected + 1\n",
                family="finite-domain-continuation",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic, not_

        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: self._predicate(left, right, PredicateValue, atomic, not_)
            )
        )

    def _predicate(self, left, right, predicate_type, atomic, not_):
        from sugar_lift_py_tests.sugar.in_op_sugar import _ground_membership

        ground = _ground_membership(left, right, self.site)
        if ground is not None:
            return ground.value.negate()
        formula = not_(
            atomic(
                "py.in",
                [
                    left.to_term(owner=str(self.site)),
                    right.to_term(owner=str(self.site)),
                ],
            )
        )
        else_bindings = ()
        coordinate = self.site.compare_left().dotted_expr_name()
        finite_value = _finite_membership_value(left, right, self.site)
        if coordinate and finite_value is not None:
            # On the false face of ``x not in (<literal domain>)``, x is
            # provably one of those literals.  Preserve that exact finite
            # construction for the sole continuation after a returning true
            # face; it is not a runtime approximation.
            else_bindings = ((coordinate, finite_value),)
        return Complete(
            predicate_type(
                formula,
                self.site,
                operand_callsites=(
                    *left.callsites(),
                    *right.callsites(),
                ),
                else_bindings=else_bindings,
            ),
        )

    def walk_children(self):
        return (self.left, self.right)


def _finite_membership_value(left, right, site):
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.outcome import Complete

    if type(right) is not TupleValue or not right.elements:
        return None
    value = right.elements[-1]
    for element in reversed(right.elements[:-1]):
        comparison = left.equals(element, site)
        if not isinstance(comparison, Complete) or not isinstance(
            comparison.value, PredicateValue
        ):
            return None
        value = GuardedValue(comparison.value.formula, element, value)
    return value
