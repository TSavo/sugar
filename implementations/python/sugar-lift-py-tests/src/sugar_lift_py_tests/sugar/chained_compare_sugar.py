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
    from sugar_lift_py_tests.ir import (
        atomic,
        identity,
        not_,
        py_ge,
        py_gt,
        py_le,
        py_lt,
    )

    # Eq / NotEq are NOT here: #4371 resolves equality per atom via
    # resolve_equality_atom (sort warrant → FOL `=` / py.eq / promotion bridge).
    if op == "Lt":
        return py_lt(left_term, right_term)
    if op == "LtE":
        return py_le(left_term, right_term)
    if op == "Gt":
        return py_gt(left_term, right_term)
    if op == "GtE":
        return py_ge(left_term, right_term)
    if op == "Is":
        return identity(left_term, right_term)
    if op == "IsNot":
        return not_(identity(left_term, right_term))
    if op == "In":
        return atomic("py.in", [left_term, right_term])
    if op == "NotIn":
        return not_(atomic("py.in", [left_term, right_term]))
    raise AssertionError(f"unsupported chain op {op}")


def _guarded_op_atom(op: str, left, right, site) -> tuple:
    """Return ``(formula, derived_bridges)`` for one chain pair.

    Equality bridges (Int/Real promotion) must ride as derived formulas, never
    as a silent cast inside the stated atom.
    """
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import and_, implies, not_

    if isinstance(left, GuardedValue):
        true_f, true_b = _guarded_op_atom(op, left.when_true, right, site)
        false_f, false_b = _guarded_op_atom(op, left.when_false, right, site)
        return (
            and_(
                [
                    implies(left.guard, true_f),
                    implies(not_(left.guard), false_f),
                ]
            ),
            (*true_b, *false_b),
        )
    if isinstance(right, GuardedValue):
        true_f, true_b = _guarded_op_atom(op, left, right.when_true, site)
        false_f, false_b = _guarded_op_atom(op, left, right.when_false, site)
        return (
            and_(
                [
                    implies(right.guard, true_f),
                    implies(not_(right.guard), false_f),
                ]
            ),
            (*true_b, *false_b),
        )
    if op in {"Eq", "NotEq"}:
        # #4371: equality vocabulary is resolved once at construction by sort.
        from sugar_lift_py_tests.floor.equality_atom import resolve_equality_atom

        formula, bridges = resolve_equality_atom(left, right, owner=str(site))
        if op == "NotEq":
            formula = not_(formula)
        return formula, bridges
    if op in {"Lt", "LtE", "Gt", "GtE"}:
        from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom

        return (
            resolve_comparison_atom(
                {"Lt": "lt", "LtE": "le", "Gt": "gt", "GtE": "ge"}[op],
                left,
                right,
                owner=str(site),
            ),
            (),
        )
    return (
        _op_atom(op, left.to_term(owner=str(site)), right.to_term(owner=str(site))),
        (),
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
        bridges: list = []
        callsites = [callsite for value in values for callsite in value.callsites()]
        for i, op in enumerate(self.ops):
            left_v = values[i]
            right_v = values[i + 1]
            atom, atom_bridges = _guarded_op_atom(op, left_v, right_v, self.site)
            atoms.append(atom)
            bridges.extend(atom_bridges)
        formula = and_(atoms) if len(atoms) > 1 else atoms[0]
        return Complete(
            PredicateValue(
                formula,
                self.site,
                operand_callsites=tuple(callsites),
                derived_formulas=tuple(bridges),
            )
        )
    def walk_children(self):
        return (self.left, *self.comparators)
