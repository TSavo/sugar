from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class InOpSugar(Sugar, role=SugarRole.TERM):
    """The ``in`` operator: ``needle in haystack``.

    Deeper floors for raises message checks:
    ``assert \"missing\" in str(exc_info.value)``.

    Emits ``py.in(needle, haystack)`` as a PredicateValue (coordinate), same
    emit-not-fold posture as EqualityOpSugar. NotIn stays a separate sugar.
    """

    left: SugarBody  # needle
    right: SugarBody  # haystack
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["In"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "InOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z in (1, 2, 3):\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return (
            _call_pair(
                name="in_return",
                owner_sugar="InOpSugar",
                truthful=prefix + "def test_a():\n    assert A(2) == 1\n",
                lying=prefix + "def test_a():\n    assert A(2) == 0\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: self._predicate(left, right)
            )
        )

    def _predicate(self, left, right):
        ground = _ground_membership(left, right, self.site)
        if ground is not None:
            return ground
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        formula = atomic(
            "py.in",
            [
                left.to_term(owner=str(self.site)),
                right.to_term(owner=str(self.site)),
            ],
        )
        then_bindings = ()
        else_bindings = ()
        if isinstance(self.right.sugar, NameSugar):
            name = self.right.sugar.name
            when_present = _membership_face(right, left, present=True)
            when_absent = _membership_face(right, left, present=False)
            if when_present is not None:
                then_bindings = ((name, when_present),)
            if when_absent is not None:
                else_bindings = ((name, when_absent),)
        return Complete(
            PredicateValue(
                formula,
                self.site,
                operand_callsites=(
                    *left.callsites(),
                    *right.callsites(),
                ),
                then_bindings=then_bindings,
                else_bindings=else_bindings,
            )
        )

    def walk_children(self):
        return (self.left, self.right)


def _membership_face(value, needle, *, present: bool):
    """Keep only joined dictionary faces compatible with a membership branch."""
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    if isinstance(value, GuardedValue):
        when_true = _membership_face(value.when_true, needle, present=present)
        when_false = _membership_face(value.when_false, needle, present=present)
        if when_true is None:
            return when_false
        if when_false is None:
            return when_true
        return GuardedValue(value.guard, when_true, when_false)
    if not isinstance(value, DictValue):
        return value
    if type(needle) not in (StringValue, TermValue):
        return value
    contains = any(
        type(key) is type(needle) and key.value == needle.value
        for key, _entry_value in value.entries
    )
    return value if contains is present else None


def _ground_membership(needle, container, site):
    """Fold membership only when every equality comparison is concrete."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.set_value import SetValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(container) not in (ListValue, SetValue, TupleValue):
        return None
    elements = container.elements
    values = [_ground_primitive_value(value) for value in (needle, *elements)]
    if any(value is _NOT_GROUND for value in values):
        return None
    present = any(values[0] == value for value in values[1:])
    return Complete(
        TrueBoolLiteralSugar(site) if present else FalseBoolLiteralSugar(site)
    )


_NOT_GROUND = object()


def _ground_primitive_value(value):
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(value) in (StringValue, TermValue):
        return value.value
    if type(value) is TrueBoolLiteralSugar:
        return True
    if type(value) is FalseBoolLiteralSugar:
        return False
    return _NOT_GROUND
