from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IsNotOpSugar(Sugar, role=SugarRole.TERM):
    """The `is not` operator. It is `not (a is b)`: identity, then the resulting
    bool/predicate negates itself. Its own sugar, its own type; no fork."""

    left: SugarBody
    right: SugarBody
    non_none_binding: str | None
    non_none_operand: str | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["IsNot"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "IsNotOpSugar":
        left = site.compare_left()
        right = site.compare_comparators()[0]
        non_none_binding = None
        non_none_operand = None
        if (
            left.observed == "Name"
            and right.observed == "PrimitiveLiteral"
            and right.literal_value() is None
        ):
            non_none_binding = left.name_id()
            non_none_operand = "left"
        elif (
            right.observed == "Name"
            and left.observed == "PrimitiveLiteral"
            and left.literal_value() is None
        ):
            non_none_binding = right.name_id()
            non_none_operand = "right"
        return cls(
            left=ctx.build_body(left, SugarRole.TERM),
            right=ctx.build_body(right, SugarRole.TERM),
            non_none_binding=non_none_binding,
            non_none_operand=non_none_operand,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z is not None:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        ground_string_prefix = (
            "def A():\n" "    return 1 if 'label' is not None else 2\n" "\n"
        )
        none_guard_refinement_prefix = (
            "def A(flag):\n"
            "    if flag == 1:\n"
            "        selected = 'seven'\n"
            "    else:\n"
            "        selected = None\n"
            "    if selected is not None:\n"
            "        return selected[0]\n"
            "    return 'n'\n"
            "\n"
        )
        return (
            _call_pair(
                name="is_not_return",
                owner_sugar="IsNotOpSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="ground_string_is_not_none",
                owner_sugar="IsNotOpSugar",
                truthful=ground_string_prefix
                + "def test_a():\n"
                + "    assert A() == 1\n",
                lying=ground_string_prefix
                + "def test_a():\n"
                + "    assert A() == 2\n",
            ),
            _call_pair(
                name="none_guard_refines_joined_binding",
                owner_sugar="IsNotOpSugar",
                truthful=none_guard_refinement_prefix
                + "def test_a():\n"
                + "    assert A(1) == 's'\n",
                lying=none_guard_refinement_prefix
                + "def test_a():\n"
                + "    assert A(1) == 'x'\n",
                family="identity-guard-binding-refinement",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome import Complete

        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.is_identical(right, self.site).and_then(
                    lambda same: same.negate().and_then(
                        lambda value: Complete(
                            self._refine_non_none_binding(value, left=left, right=right)
                        )
                    )
                )
            )
        )

    def _refine_non_none_binding(self, value, *, left, right):
        """Carry a proven ``is not None`` face into the true branch scope."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        if not isinstance(value, PredicateValue) or self.non_none_binding is None:
            return value
        operand = left if self.non_none_operand == "left" else right
        refined = _without_none_face(operand)
        if refined is None:
            return value
        return replace(
            value,
            then_bindings=(
                *value.then_bindings,
                (self.non_none_binding, refined),
            ),
        )

    def walk_children(self):
        return (self.left, self.right)


def _without_none_face(value):
    """Project the exact non-None faces of a construction-time branch join."""
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.none_value import NoneValue

    if isinstance(value, NoneValue):
        return None
    if not isinstance(value, GuardedValue):
        return value
    when_true = _without_none_face(value.when_true)
    when_false = _without_none_face(value.when_false)
    if when_true is None:
        return when_false
    if when_false is None:
        return when_true
    return GuardedValue(value.guard, when_true, when_false)
