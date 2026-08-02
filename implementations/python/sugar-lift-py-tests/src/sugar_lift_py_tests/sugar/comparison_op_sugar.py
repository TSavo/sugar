"""A comparison `<left> <op> <right>` for the ordering family and `!=`.

`==` keeps its own sugar (EqualityOpSugar, which also refines); this owns the
rest: the node carries the operator, and this routes the reduced left value to
the floor method that operator names (`less_than`, `greater_equal`, ...). Each
is `py.lt` / `py.le` / ... -- vendor comparison, not SMT `<`, so the sort
universe adjudicates (same NaN/reflexivity split as py.eq). `!=` is `==` negated:
Python `a != b` is `not (a == b)`, so it stands on the equals floor and negates
that predicate -- never a bespoke inequality atom.

Compare construction is partitioned by law — not one monomorphic refusal:

- **ordering** (`<` `<=` `>` `>=`): rich-method dispatch may complete or raise
- **membership** (`in` / `not in`): container owns ``__contains__`` / iteration
- **equality** (`==` / `!=`): ``__eq__`` / ``__ne__`` may complete or raise
- **identity** (`is` / `is not`): total object identity; never user-code dispatch
- **chaining** (`a < b < c`): pair laws composed under short-circuit ``And`` at
  ``Compare._construct_sugar`` (BoolOpSugar over adjacent pair sugars)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
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


class CompareLaw(str, Enum):
    """Separate Compare construction mechanisms — laws differ, so partitions do."""

    ORDERING = "ordering"
    MEMBERSHIP = "membership"
    EQUALITY = "equality"
    IDENTITY = "identity"
    CHAINING = "chaining"


_LAW_BY_OP: dict[str, CompareLaw] = {
    "Lt": CompareLaw.ORDERING,
    "LtE": CompareLaw.ORDERING,
    "Gt": CompareLaw.ORDERING,
    "GtE": CompareLaw.ORDERING,
    "In": CompareLaw.MEMBERSHIP,
    "NotIn": CompareLaw.MEMBERSHIP,
    "Eq": CompareLaw.EQUALITY,
    "NotEq": CompareLaw.EQUALITY,
    "Is": CompareLaw.IDENTITY,
    "IsNot": CompareLaw.IDENTITY,
}

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


def compare_law_for(op_kind: str) -> CompareLaw:
    """The construction law that owns one comparison operator kind."""
    try:
        return _LAW_BY_OP[op_kind]
    except KeyError as error:
        raise KeyError(f"no Compare law for operator kind {op_kind!r}") from error


def partition_key_for_law(law: CompareLaw, site, op_kind: str) -> tuple:
    """Law-scoped ExitSet partition coordinate (not one shared monomorphic key)."""
    return (f"compare.{law.value}.dispatch", str(site), op_kind)


def publish_undecided_comparison_edges(left, right, site, op_kind: str, outcome):
    """Dispatch to the law-specific dual-edge publisher for ``op_kind``."""
    law = compare_law_for(op_kind)
    if law is CompareLaw.ORDERING:
        return publish_undecided_ordering_edges(left, right, site, op_kind, outcome)
    if law is CompareLaw.MEMBERSHIP:
        return publish_undecided_membership_edges(left, right, site, op_kind, outcome)
    if law is CompareLaw.EQUALITY:
        return publish_undecided_equality_edges(left, right, site, op_kind, outcome)
    # Identity never dual-edges: ``is`` / ``is not`` cannot invoke user code.
    return outcome


def publish_undecided_ordering_edges(left, right, site, op_kind: str, outcome):
    """Ordering law: never dual-edge residual FOL invent (LAW_OF_ONE).

    Floor undecided doors throw named; ground doors construct Sugar or
    authenticated RaiseValue. A residual ``Complete(PredicateValue)`` is OUR
    fabrication second door — construction panic, not a nameless dual-edge
    ExitSet. Equality still dual-edges via the shared helper; membership uses
    :func:`publish_undecided_membership_edges`.

    Retirement path: when no path can mint ordering PredicateValue, this
    membrane only passes through and may shrink to ``return outcome``.
    """
    del left, right
    from sugar_lift_py_tests.floor import PredicateValue
    from sugar_lift_py_tests.outcome import Complete

    if not isinstance(outcome, Complete) or not isinstance(
        outcome.value, PredicateValue
    ):
        return outcome

    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="publish_undecided_ordering_edges",
        blame=site,
        observed=(
            f"residual Complete(PredicateValue) on ordering desugar ({op_kind})"
        ),
        requested=(
            "named SugarNotWritten for undecided operands, or Sugar-owned "
            "TrueBool/FalseBool/RaiseValue for decided ground"
        ),
        fix=(
            "LAW_OF_ONE: never dual-edge or sole-complete FOL invent for "
            "ordering; construct Sugar on ground arms; throw named when "
            "runtime types are undecided"
        ),
    )


def publish_undecided_membership_edges(left, right, site, op_kind: str, outcome):
    """Membership law: undecided ``__contains__`` / iteration is a two-face partition.

    Operand order is needle then container (the producer already swapped for
    ``in`` / ``not in`` so the floor call is ``container.contains(item)``).
    """
    return _publish_undecided_dispatch_edges(
        left,
        right,
        site,
        op_kind,
        outcome,
        law=CompareLaw.MEMBERSHIP,
    )


def publish_undecided_equality_edges(left, right, site, op_kind: str, outcome):
    """Equality law: undecided ``__eq__`` / ``__ne__`` is a two-face partition."""
    return _publish_undecided_dispatch_edges(
        left,
        right,
        site,
        op_kind,
        outcome,
        law=CompareLaw.EQUALITY,
    )


def construct_identity_comparison(left, right, site, *, negated: bool = False):
    """Identity law: total object identity; never a dual-edge raise partition.

    Python ``is`` / ``is not`` does not dispatch user code, so there is no
    exceptional face to publish. The floor's ``is_identical`` atom is the whole
    meaning; ``site`` is the identity floor's blame coordinate.
    """
    outcome = left.is_identical(right, site)
    if not negated:
        return outcome
    return outcome.and_then(lambda predicate: predicate.negate())


def defer_formal_native_operation(left, right, site, *, operator: str):
    """Preserve one formal-bound native operation for caller discharge.

    A formal's runtime type is supplied outside this frame.  Constructing an
    immediate normal or exceptional face here would therefore invent caller
    testimony.  The shared carrier records the ordered Floor operation and
    lets authenticated actual operands select its real ExitSet later.
    """
    left_coordinate = getattr(left, "formal_coordinate", None)
    right_coordinate = getattr(right, "formal_coordinate", None)
    if left_coordinate is None and right_coordinate is None:
        return None

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    return NativeOperationExitCarrierV1.mint(
        site=site,
        operator=operator,
        operands=(left, right),
        coordinates=(left_coordinate, right_coordinate),
    )


def _publish_undecided_dispatch_edges(
    left,
    right,
    site,
    op_kind: str,
    outcome,
    *,
    law: CompareLaw,
):
    """Shared dual-edge construction; partition key is law-scoped.

    Ordering, membership, and equality are not total over undecided runtime
    types: Python may select a rich method that completes or raises. Emitting
    only the solver atom invents completion; inventing ``TypeError`` invents an
    exception identity. The producer therefore emits complementary completed
    and halted edges without inventing an exception type.

    Decided pairs fall through to the floor's ground construction (RaiseValue
    TypeError or honest completion). Identity is not routed here.
    """
    if law is CompareLaw.IDENTITY or law is CompareLaw.CHAINING:
        return outcome

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

    # Undecided compare must not mint a nameless RaiseEffect (sin-cluster-2 /
    # constructor climb). Throwing is honorable unfinished identity work;
    # dual-edge ExitSet with undetermined halt is forbidden.
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=f"ComparisonOpSugar.{op_kind}",
        blame=site,
        observed=(
            "undecided binary compare reached dual-edge path without "
            "authenticated exception_type_coordinate"
        ),
        requested=(
            "decided ground TypeError via ground_type_error, or named refusal "
            "before ExitSet mint"
        ),
        fix=(
            "do not construct RaiseEffect without exception_type_coordinate; "
            "ground decided pairs use ground_type_error; undecided native "
            "dispatch throws before dual-edge fabrication"
        ),
    )


@dataclass(frozen=True)
class ComparisonOpSugar(ConstructedTermSugar):
    op_kind: str
    left: ConstructedTermSugar
    right: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        if self.op_kind not in COMPARISON_KINDS:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ComparisonOpSugar",
                blame=self.site,
                observed=f"comparison operator {self.op_kind!r} has no ComparisonOpSugar arm",
                requested="a written comparison kind in COMPARISON_KINDS",
                fix=f"enroll {self.op_kind!r} in ComparisonOpSugar or refuse earlier",
            )
        require_constructed_term_sugar(self.left, owner="ComparisonOpSugar.left")
        require_constructed_term_sugar(self.right, owner="ComparisonOpSugar.right")

    @classmethod
    def witnesses(cls):
        return _boolop_wrapped_pair(
            name="comparison_lt",
            owner_sugar="ComparisonOpSugar",
            truthful="1 < 2",
            lying="2 < 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:comparison-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.op_kind),
                self.left.to_term(owner=owner),
                self.right.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        left = self.left.desugar(ctx)
        right = lambda l: self.right.desugar(ctx).and_then(  # noqa: E731
            lambda r: self._apply(
                l.project_operation_receiver(
                    ctx, owner="ComparisonOpSugar left operation receiver"
                ),
                r.project_operation_receiver(
                    ctx, owner="ComparisonOpSugar right operation receiver"
                ),
            )
        )
        return left.and_then(right)

    def _membership(self, container, item):
        """Membership law: container owns containment; undecided dispatch dual-edges."""
        deferred = defer_formal_native_operation(
            container, item, self.site, operator="contains"
        )
        if deferred is not None:
            return deferred
        outcome = container.contains(item, self.site)
        return publish_undecided_membership_edges(
            item, container, self.site, self.op_kind, outcome
        )

    def _ordering(self, left, right):
        """Ordering law: left owns the rich method; undecided dispatch dual-edges."""
        method = COMPARE_METHODS[self.op_kind]
        deferred = defer_formal_native_operation(
            left, right, self.site, operator=method
        )
        if deferred is not None:
            return deferred
        return publish_undecided_ordering_edges(
            left,
            right,
            self.site,
            self.op_kind,
            getattr(left, method)(right, self.site),
        )

    def _apply(self, left, right):
        if self.op_kind == "NotEq":
            # Equality law: a != b is not (a == b); dual-edge then negate.
            deferred = defer_formal_native_operation(
                left, right, self.site, operator="equals"
            )
            if deferred is not None:
                return deferred.and_then(lambda predicate: predicate.negate())
            return publish_undecided_equality_edges(
                left,
                right,
                self.site,
                self.op_kind,
                left.equals(right, self.site),
            ).and_then(lambda predicate: predicate.negate())
        if self.op_kind == "Is":
            return construct_identity_comparison(
                left, right, self.site, negated=False
            )
        if self.op_kind == "IsNot":
            return construct_identity_comparison(
                left, right, self.site, negated=True
            )
        if self.op_kind == "In":
            # a in b: the CONTAINER (right) owns membership -- b.contains(a).
            return self._membership(right, left)
        if self.op_kind == "NotIn":
            # a not in b is not (a in b): membership floor, negated.
            return self._membership(right, left).and_then(
                lambda predicate: predicate.negate()
            )
        return self._ordering(left, right)
