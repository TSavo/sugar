from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BoolOpSugar(Sugar, role=SugarRole.TERM):
    """`a and b` / `a or b`. Python short-circuit: the result IS an operand value,
    not a coerced bool. `1 and 2` is 2; `0 or 3` is 3. Reduce left-to-right; fold
    via the truth floor when ground; emit py.and / py.or when symbolic."""

    kind: str  # "and" | "or"
    operands: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BoolOp"

    @classmethod
    def new(cls, site, ctx) -> "BoolOpSugar":
        # Operands are factory-built (audited), never reduced here.
        return cls(
            kind=site.boolop_op_kind(),
            operands=tuple(
                ctx.build_body(value, SugarRole.TERM) for value in site.boolop_values()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `1 and 2 == 2` is `1 and (2 == 2)` -> True, so the if-face returns z.
        # Truthful rides 5; lying asserts 0 -- the pair proves the lift
        # discriminates on the short-circuit face.
        prefix = (
            "def A(z):\n"
            "    if 1 and 2 == 2:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="bool_op_return",
            owner_sugar="BoolOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Left-to-right short-circuit over the operands.
        if not self.operands:
            from sugar_lift_py_tests.factory import factory_panic, FactoryGapInfo, GapKind, GapLocus

            factory_panic(
                FactoryGapInfo(
                    owner="BoolOpSugar",
                    blame=str(self.site),
                    observed="BoolOp",
                    requested="at least one operand",
                    fix="BoolOp with empty values is not Python",
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            )
        return self._reduce_from(0, ctx)

    def _reduce_from(self, index: int, ctx: object) -> Outcome:
        return self.operands[index].reduce(ctx).and_then(
            lambda value: self._after_operand(value, index, ctx)
        )

    def _after_operand(self, value, index: int, ctx: object) -> Outcome:
        # Last operand is always the result once reached.
        if index == len(self.operands) - 1:
            return Complete(value)

        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        # A predicate already stands as a condition -- cannot ground-fold; emit.
        if type(value) is PredicateValue:
            return self._emit_coordinate_from(value, index, ctx)

        # Ask the truth floor; True/False literals own the short-circuit faces.
        return value.truth(self.site).and_then(
            lambda standing: self._on_truth(value, standing, index, ctx)
        )

    def _on_truth(self, value, standing, index: int, ctx: object) -> Outcome:
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if self.kind == "and":
            # Falsy left: result IS left (do not evaluate the rest).
            if type(standing) is FalseBoolLiteralSugar:
                return Complete(value)
            # Truthy left: result IS the rest of the chain.
            if type(standing) is TrueBoolLiteralSugar:
                return self._reduce_from(index + 1, ctx)
        else:
            # or: truthy left: result IS left; falsy left: continue.
            if type(standing) is TrueBoolLiteralSugar:
                return Complete(value)
            if type(standing) is FalseBoolLiteralSugar:
                return self._reduce_from(index + 1, ctx)

        # Symbolic / non-ground standing: emit the conjunction coordinate.
        return self._emit_coordinate_from(value, index, ctx)

    def _emit_coordinate_from(self, first, index: int, ctx: object) -> Outcome:
        # Reduce the remaining operands, then build py.and / py.or over terms.
        return self._collect_rest(
            self.operands[index + 1 :],
            (first,),
            ctx,
        )

    def _collect_rest(
        self, remaining: tuple, accumulated: tuple, ctx: object
    ) -> Outcome:
        if not remaining:
            return Complete(self._coordinate(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect_rest(tuple(rest), (*accumulated, value), ctx)
        )

    def _coordinate(self, values: tuple):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import and_, ctor, or_

        # Predicate-shaped operands: FOL conjunction / disjunction.
        if values and all(type(v) is PredicateValue for v in values):
            formulas = [v.formula for v in values]
            formula = and_(formulas) if self.kind == "and" else or_(formulas)
            callsites = tuple(
                site for v in values for site in v.operand_callsites
            )
            return PredicateValue(formula, self.site, callsites)

        # Value-shaped: py.and / py.or coordinate over operand terms.
        name = "py.and" if self.kind == "and" else "py.or"
        terms = [v.to_term(owner=str(self.site)) for v in values]
        return SymbolicValue(ctor(name, terms))

    def walk_children(self):
        return self.operands
