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

    def _apply(self, left, right):
        if self.op_kind == "NotEq":
            # a != b is not (a == b): stand on the equals floor, negate.
            return left.equals(right, self.site).and_then(
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
            return right.contains(left, self.site)
        if self.op_kind == "NotIn":
            # a not in b is not (a in b): membership floor, negated.
            return right.contains(left, self.site).and_then(
                lambda predicate: predicate.negate()
            )
        method = COMPARE_METHODS[self.op_kind]
        return getattr(left, method)(right, self.site)
