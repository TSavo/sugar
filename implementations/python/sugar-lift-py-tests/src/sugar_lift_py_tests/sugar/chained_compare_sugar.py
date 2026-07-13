from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

_CHAIN_OPS = frozenset(
    {
        "Eq",
        "NotEq",
        "Lt",
        "LtE",
        "Gt",
        "GtE",
        "Is",
        "IsNot",
        "In",
        "NotIn",
    }
)


def _op_atom(op: str, left_term, right_term):
    from sugar_lift_py_tests.ir import atomic, identity, not_, py_eq, py_lt

    if op == "Eq":
        return py_eq(left_term, right_term)
    if op == "NotEq":
        return not_(py_eq(left_term, right_term))
    if op == "Lt":
        return py_lt(left_term, right_term)
    if op == "LtE":
        return not_(py_lt(right_term, left_term))
    if op == "Gt":
        return py_lt(right_term, left_term)
    if op == "GtE":
        return not_(py_lt(left_term, right_term))
    if op == "Is":
        return identity(left_term, right_term)
    if op == "IsNot":
        return not_(identity(left_term, right_term))
    if op == "In":
        return atomic("py.in", [left_term, right_term])
    if op == "NotIn":
        return not_(atomic("py.in", [left_term, right_term]))
    raise AssertionError(f"unsupported chain op {op}")


def _guarded_op_atom(op: str, left, right, site):
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import and_, implies, not_

    if isinstance(left, GuardedValue):
        return and_(
            [
                implies(
                    left.guard,
                    _guarded_op_atom(op, left.when_true, right, site),
                ),
                implies(
                    not_(left.guard),
                    _guarded_op_atom(op, left.when_false, right, site),
                ),
            ]
        )
    if isinstance(right, GuardedValue):
        return and_(
            [
                implies(
                    right.guard,
                    _guarded_op_atom(op, left, right.when_true, site),
                ),
                implies(
                    not_(right.guard),
                    _guarded_op_atom(op, left, right.when_false, site),
                ),
            ]
        )
    return _op_atom(
        op,
        left.to_term(owner=str(site)),
        right.to_term(owner=str(site)),
    )


@dataclass(frozen=True)
class ChainedCompareSugar(Sugar, role=SugarRole.TERM):
    """Chained comparisons: ``a < b < c`` → conjunction of pairwise atoms.

    Single-op Compare stays with EqualityOpSugar / InOpSugar / …
    Two-or-more ops are owned here so they are not an unowned Compare gap.
    """

    left: SugarBody
    ops: tuple[str, ...]
    comparators: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Compare":
            return False
        ops = site.compare_ops()
        if len(ops) < 2:
            return False
        return all(op in _CHAIN_OPS for op in ops) and len(
            site.compare_comparators()
        ) == len(ops)

    @classmethod
    def new(cls, site, ctx) -> "ChainedCompareSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            ops=tuple(site.compare_ops()),
            comparators=tuple(
                ctx.build_body(c, SugarRole.TERM) for c in site.compare_comparators()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if 0 < z < 10:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="chained_compare_return",
            owner_sugar="ChainedCompareSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left_v: self._reduce_comparators(0, (left_v,), ctx)
        )

    def _reduce_comparators(self, i: int, values: tuple, ctx: object) -> Outcome:
        if i < len(self.comparators):
            return (
                self.comparators[i]
                .reduce(ctx)
                .and_then(lambda v: self._reduce_comparators(i + 1, (*values, v), ctx))
            )
        return self._emit(values)

    def _emit(self, values: tuple) -> Outcome:
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import and_

        atoms = []
        callsites = [callsite for value in values for callsite in value.callsites()]
        for i, op in enumerate(self.ops):
            left_v = values[i]
            right_v = values[i + 1]
            atoms.append(_guarded_op_atom(op, left_v, right_v, self.site))
        formula = and_(atoms) if len(atoms) > 1 else atoms[0]
        return Complete(
            PredicateValue(
                formula,
                self.site,
                operand_callsites=tuple(callsites),
            )
        )

    def walk_children(self):
        return (self.left, *self.comparators)
