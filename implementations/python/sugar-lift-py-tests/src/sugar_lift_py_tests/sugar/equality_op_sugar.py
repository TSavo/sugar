from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class EqualityOpSugar(ConstructedTermSugar):
    """The `==` operator. One of the comparison family (`!=`, `<`, ... are their own
    sugars, their own types -- no operator field to switch on). It reduces both sides
    and asks the left whether it equals the right: the left stands on the equals floor
    and gives back a True or False literal."""

    left: ConstructedTermSugar
    right: ConstructedTermSugar
    site: object = dataclass_field(compare=False)
    # The dotted PLACE this pair's left operand names (`x`, `a.b.c`), or None if
    # it names none. Read off the tree by `Compare._construct_sugar`, because
    # only construction knows which operand is this pair's left.
    left_coordinate: object = None

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.left, owner="EqualityOpSugar.left")
        require_constructed_term_sugar(self.right, owner="EqualityOpSugar.right")

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str) -> Term:
        """Project the fixed equality operator and ordered operands canonically."""
        from sugar_lift_py_tests.ir import ctor, str_const

        operands = [
            self.left.to_term(owner=owner),
            self.right.to_term(owner=owner),
        ]
        coordinate = self.left_coordinate
        if coordinate is None:
            refinement = ctor("python:no-refinement-coordinate", ())
        else:
            cid = coordinate.cid
            refinement = ctor(
                "python:refinement-coordinate",
                (str_const(cid),),
                symbol_kind="coordinate",
            )

        return ctor(
            "python:equality-op-construction",
            (
                str_const("equals"),
                self.occurrence_term(owner=owner),
                refinement,
                ctor(
                    "python:equality-op-operands",
                    tuple(operands),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce both sides; the left, standing on the equals floor, answers
        # whether it equals the right. That is all `==` desugars to.
        return self.left.desugar(ctx).and_then(
            lambda left: self.right.desugar(ctx).and_then(
                lambda right: self.apply_reduced(left, right, ctx)
            )
        )

    def apply_reduced(self, left, right, ctx: object = None) -> Outcome:
        """Apply equality/refinement to operands already evaluated once."""
        return _equals_and_refine(
            left, right, self.site, ctx, self.left_coordinate
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
    from sugar_lift_py_tests.sugar.comparison_op_sugar import (
        defer_formal_native_operation,
        publish_undecided_equality_edges,
    )

    deferred = defer_formal_native_operation(left, right, site, operator="equals")
    if deferred is not None:
        return deferred

    outcome = left.equals(right, site)

    from sugar_lift_py_tests.floor import CallSiteValue, PredicateValue
    from sugar_lift_py_tests.outcome import Complete

    if isinstance(left, CallSiteValue):
        residue = left.derived_equality_residue(ctx)
        if residue is not None and (
            isinstance(outcome, Complete)
            and isinstance(outcome.value, PredicateValue)
        ):
            outcome = Complete(
                replace(
                    outcome.value,
                    derived_formulas=(*outcome.value.derived_formulas, residue),
                )
            )
    # Equality law: dual-edge when either operand type is undecided.
    return publish_undecided_equality_edges(
        left,
        right,
        site,
        "Eq",
        outcome,
    )
