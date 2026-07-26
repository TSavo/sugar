from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class EqualityOpSugar(Sugar):
    """The `==` operator. One of the comparison family (`!=`, `<`, ... are their own
    sugars, their own types -- no operator field to switch on). It reduces both sides
    and asks the left whether it equals the right: the left stands on the equals floor
    and gives back a True or False literal."""

    left: Sugar
    right: Sugar
    site: object = dataclass_field(compare=False)
    # The dotted PLACE this pair's left operand names (`x`, `a.b.c`), or None if
    # it names none. Read off the tree by `Compare._construct_sugar`, because
    # only construction knows which operand is this pair's left.
    left_coordinate: object = None

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce both sides; the left, standing on the equals floor, answers
        # whether it equals the right. That is all `==` desugars to.
        return self.left.desugar(ctx).and_then(
            lambda left: self.right.desugar(ctx).and_then(
                lambda right: _equals_and_refine(
                    left, right, self.site, ctx, self.left_coordinate
                )
            )
        )


def _finite_equality_face(value, peer, *, matches: bool):
    """Filter an exact construction-time finite join by a ground equality."""
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    if isinstance(value, GuardedValue):
        when_true = _finite_equality_face(value.when_true, peer, matches=matches)
        when_false = _finite_equality_face(value.when_false, peer, matches=matches)
        if when_true is None:
            return when_false
        if when_false is None:
            return when_true
        return GuardedValue(value.guard, when_true, when_false)
    if type(value) not in (StringValue, TermValue) or type(peer) is not type(value):
        return value
    equal = value.value == peer.value
    return value if equal is matches else None


def _equals_and_refine(left, right, site, ctx, left_coordinate):
    outcome = _equals_with_derived_residue(left, right, site, ctx)
    from sugar_lift_py_tests.floor import PredicateValue
    from sugar_lift_py_tests.outcome import Complete

    if not isinstance(outcome, Complete) or not isinstance(
        outcome.value, PredicateValue
    ):
        return outcome
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    if not isinstance(left, GuardedValue) or type(right) not in (
        StringValue,
        TermValue,
    ):
        return outcome
    coordinate = left_coordinate
    if not coordinate:
        return outcome
    matching = _finite_equality_face(left, right, matches=True)
    remaining = _finite_equality_face(left, right, matches=False)
    matching_binding = ((coordinate, matching),) if matching is not None else ()
    remaining_binding = ((coordinate, remaining),) if remaining is not None else ()
    return Complete(
        replace(
            outcome.value,
            then_bindings=(
                *outcome.value.then_bindings,
                *matching_binding,
            ),
            else_bindings=(
                *outcome.value.else_bindings,
                *remaining_binding,
            ),
        )
    )


def _equals_with_derived_residue(left, right, site, ctx):
    outcome = left.equals(right, site)

    from sugar_lift_py_tests.floor import CallSiteValue, PredicateValue
    from sugar_lift_py_tests.outcome import Complete

    if not isinstance(left, CallSiteValue):
        return outcome
    residue = left.derived_equality_residue(ctx)
    if residue is None or not (
        isinstance(outcome, Complete) and isinstance(outcome.value, PredicateValue)
    ):
        return outcome
    return Complete(
        replace(
            outcome.value,
            derived_formulas=(*outcome.value.derived_formulas, residue),
        )
    )
