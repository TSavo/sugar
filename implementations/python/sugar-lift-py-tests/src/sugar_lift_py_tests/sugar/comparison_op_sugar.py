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

_OPERATOR_COORDINATE = {
    "Eq": "==",
    "NotEq": "!=",
    "Lt": "<",
    "LtE": "<=",
    "Gt": ">",
    "GtE": ">=",
    "In": "in",
    "NotIn": "not in",
}


def refuse_undecided_comparison(left, right, site, op_kind: str) -> None:
    """Keep undecided native comparison/containment dispatch at the producer.

    Ordering and membership are not total over undecided runtime types:
    Python may select a rich method that completes or raises (``Series`` vs
    ``str`` raises ``TypeError``; unknown containers may raise from
    ``__contains__``). Emitting ``py.lt`` / ``py.in`` invents completion;
    inventing ``TypeError`` invents an exception identity. Both stay refused
    until native operand types are source-authenticated — the same producer
    law BinOp/BoolOp already own.

    Equality is different: ``==`` / ``!=`` remain total solver coordinates for
    symbolic and ground pairs (``py.eq``), so equality only refuses an
    unexecuted call result whose ``__eq__`` body is itself undecided.
    """
    denotes_left = getattr(left, "denotes_value", None)
    denotes_right = getattr(right, "denotes_value", None)
    if not callable(denotes_left) or not callable(denotes_right):
        return
    if not (denotes_left() and denotes_right()):
        return

    if op_kind in {"Eq", "NotEq"}:
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if not isinstance(left, CallSiteValue) and not isinstance(right, CallSiteValue):
            return
    else:
        decided_left = getattr(left, "runtime_type_is_decided", None)
        decided_right = getattr(right, "runtime_type_is_decided", None)
        if not callable(decided_left) or not callable(decided_right):
            return
        if decided_left() and decided_right():
            return

    from sugar_lift_py_tests.gap.info import GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    operator = _OPERATOR_COORDINATE[op_kind]
    construction_panic_gap(
        owner="comparison_operation_exception_floor",
        blame=site,
        observed=(f"{type(left).__name__} {operator} {type(right).__name__}"),
        requested=(
            "source-visible native comparison testimony selecting completion "
            "or an authenticated exceptional exit"
        ),
        fix=(
            "preserve the undecided third value at the Compare producer; "
            "resolve native operand types and their comparison/containment "
            "bodies from source, or retain this named refusal without "
            "inventing an exception identity"
        ),
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )


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
        refuse_undecided_comparison(item, container, self.site, self.op_kind)
        return container.contains(item, self.site)

    def _apply(self, left, right):
        if self.op_kind not in {"Is", "IsNot", "In", "NotIn"}:
            refuse_undecided_comparison(left, right, self.site, self.op_kind)
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
            return self._membership(right, left)
        if self.op_kind == "NotIn":
            # a not in b is not (a in b): membership floor, negated.
            return self._membership(right, left).and_then(
                lambda predicate: predicate.negate()
            )
        method = COMPARE_METHODS[self.op_kind]
        return getattr(left, method)(right, self.site)
