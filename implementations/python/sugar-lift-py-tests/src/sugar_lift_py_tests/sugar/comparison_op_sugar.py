"""A comparison `<left> <op> <right>` for the ordering family and `!=`.

`==` keeps its own sugar (EqualityOpSugar, which also refines); this owns the
rest: the node carries the operator, and this routes the reduced left value to
the floor method that operator names (`less_than`, `greater_equal`, ...). Each
is `py.lt` / `py.le` / ... -- vendor comparison, not SMT `<`, so the sort
universe adjudicates (same NaN/reflexivity split as py.eq). `!=` is `==` negated:
Python `a != b` is `not (a == b)`, so it stands on the equals floor and negates
that predicate -- never a bespoke inequality atom.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _boolop_wrapped_pair

# Comparison operator kind -> the floor method that owns its meaning. `Eq` is
# absent (EqualityOpSugar owns it); `NotEq` is absent (equals + negate, below).
COMPARE_METHODS: dict[str, str] = {
    "Lt": "less_than",
    "LtE": "less_equal",
    "Gt": "greater_than",
    "GtE": "greater_equal",
}

# Every comparison kind this sugar owns (Eq is EqualityOpSugar's, not here).
# `NotEq`/`IsNot`/`NotIn` are their positive form negated; `Is` stands on the
# identity floor; `In` on the membership floor (the CONTAINER is the right
# operand: `x in xs` is `xs.contains(x)`).
COMPARISON_KINDS = frozenset(COMPARE_METHODS) | {"NotEq", "Is", "IsNot", "In", "NotIn"}

_DISPATCH_RAISE_COORDINATE = {
    "Eq": "python.eq_dispatch_raises",
    "NotEq": "python.eq_dispatch_raises",
    "Lt": "python.lt_dispatch_raises",
    "LtE": "python.le_dispatch_raises",
    "Gt": "python.gt_dispatch_raises",
    "GtE": "python.ge_dispatch_raises",
    "In": "python.contains_dispatch_raises",
    "NotIn": "python.contains_dispatch_raises",
}


def _publish_undecided_dispatch_edges(left, right, site, op_kind: str, outcome):
    """Mechanical two-face constructor shared by the three dispatch laws.

    Ordering, membership, and equality are not total over undecided runtime types:
    Python may select a rich method that completes or raises (``Series`` vs
    ``str`` raises ``TypeError``; unknown containers may raise from
    ``__contains__``). Emitting only ``py.lt`` / ``py.in`` invents totality;
    inventing ``TypeError`` invents an exception identity. The undecided
    dispatch therefore retains both guarded faces.

    Equality is total only after both native operand types are decided.  An
    undecided value may dispatch ``__eq__`` / ``__ne__`` that completes or
    raises.  The producer owns that two-way split: the completed face retains
    the operator's solver atom and the halted face retains a source-cited raise
    occurrence whose exception identity remains undecided.  Identity is not
    routed here because Python ``is`` / ``is not`` cannot invoke user code.
    """
    denotes_left = getattr(left, "denotes_value", None)
    denotes_right = getattr(right, "denotes_value", None)
    if not callable(denotes_left) or not callable(denotes_right):
        return outcome
    if not (denotes_left() and denotes_right()):
        return outcome

    decided_left = getattr(left, "runtime_type_is_decided", None)
    decided_right = getattr(right, "runtime_type_is_decided", None)
    if not callable(decided_left) or not callable(decided_right):
        return outcome
    if decided_left() and decided_right():
        return outcome

    from sugar_lift_py_tests.floor import PredicateValue
    from sugar_lift_py_tests.outcome import Complete, ExitSet
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        Halted,
        complement_guard,
        partition,
    )

    if not isinstance(outcome, Complete) or not isinstance(
        outcome.value, PredicateValue
    ):
        return outcome

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.ir import atomic

    dispatch_raises = atomic(
        _DISPATCH_RAISE_COORDINATE[op_kind],
        [
            left.to_term(owner=f"{op_kind} left operand"),
            right.to_term(owner=f"{op_kind} right operand"),
        ],
    )
    halted_face, completed_face = partition(
        ("comparison-native-dispatch", str(site), op_kind)
    )
    effect = RaiseEffect(
        blame=str(site),
        occurrence=str(site),
        producer_node_owner="Compare",
    )
    return ExitSet(
        (
            Halted(dispatch_raises, effect, faces=frozenset({halted_face})),
            Completed(
                complement_guard(dispatch_raises),
                outcome.value,
                frozenset({completed_face}),
            ),
        )
    ).normalize()


def publish_undecided_equality_edges(left, right, site, op_kind: str, outcome):
    """Keep ``py.eq`` beside the possible ``__eq__``/``__ne__`` halt."""
    assert op_kind in {"Eq", "NotEq"}
    return _publish_undecided_dispatch_edges(left, right, site, op_kind, outcome)


def publish_undecided_contains_edges(item, container, site, op_kind: str, outcome):
    """Keep authenticated ``contains`` completion beside its possible halt."""
    assert op_kind in {"In", "NotIn"}
    return _publish_undecided_dispatch_edges(
        item, container, site, op_kind, outcome
    )


def publish_undecided_ordering_edges(left, right, site, op_kind: str, outcome):
    """Keep rich-comparison completion beside possible native dispatch halt."""
    assert op_kind in COMPARE_METHODS
    return _publish_undecided_dispatch_edges(left, right, site, op_kind, outcome)


@dataclass(frozen=True)
class ComparisonOpSugar(Sugar):
    op_kind: str
    left: Sugar
    right: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _boolop_wrapped_pair(
            name="comparison_lt",
            owner_sugar="ComparisonOpSugar",
            truthful="1 < 2",
            lying="2 < 1",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        left = self.left.desugar(ctx)
        right = lambda l: self.right.desugar(ctx).and_then(  # noqa: E731
            lambda r: self._apply(l, r)
        )
        return left.and_then(right)

    def _membership(self, container, item):
        """Dispatch membership only when native operand types are decided.

        An undecided container or needle denotes a Python value, but which
        ``__contains__`` / iteration path Python would select — and whether it
        raises — is a third value. Emitting ``py.in`` invents completion;
        inventing ``TypeError`` invents an exit. Keep that undecided dispatch
        loud at the Compare producer.
        """
        outcome = container.contains(item, self.site)
        return publish_undecided_contains_edges(
            item, container, self.site, self.op_kind, outcome
        )

    def _apply(self, left, right):
        if self.op_kind == "NotEq":
            # a != b is not (a == b): stand on the equals floor, negate.
            return publish_undecided_equality_edges(
                left,
                right,
                self.site,
                self.op_kind,
                left.equals(right, self.site),
            ).and_then(
                lambda predicate: predicate.negate()
            )
        if self.op_kind == "Is":
            # a is b: object identity, stands on the is_identical floor.
            return left.is_identical(right, self.site)
        if self.op_kind == "IsNot":
            # a is not b is not (a is b): identity floor, negated.
            return left.is_identical(right, self.site).and_then(
                lambda predicate: predicate.negate()
            )
        if self.op_kind == "In":
            # a in b: the CONTAINER (right) owns membership -- b.contains(a).
            return self._membership(right, left)
        if self.op_kind == "NotIn":
            # a not in b is not (a in b): membership floor, negated.
            return self._membership(right, left).and_then(
                lambda predicate: predicate.negate()
            )
        method = COMPARE_METHODS[self.op_kind]
        return publish_undecided_ordering_edges(
            left,
            right,
            self.site,
            self.op_kind,
            getattr(left, method)(right, self.site),
        )
