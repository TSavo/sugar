from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus

_UNARY_OPS = frozenset({"USub", "UAdd", "Not", "Invert"})


@dataclass(frozen=True)
class UnaryOpSugar(Sugar, role=SugarRole.TERM, comes_before=("NotOpSugar",)):
    """Unary operators: `-x`, `+x`, `not x`, `~x`.

    Fold when ground, emit a coordinate when symbolic, panic only inside
    to_term when the operand cannot enter FOL. Dispatches per op:

    * `not`: truth floor then negate (Python truthiness, not a re-derived bool)
    * `-` (USub): unary_minus floor -- TermValue folds, SymbolicValue py.neg
    * `+` (UAdd): unary_plus floor -- ground fold, symbolic identity
    * `~` (Invert): bitwise_invert floor -- int fold, SymbolicValue py.invert

    Comes before NotOpSugar so this arm owns all four UnaryOp shapes.
    """

    op: str
    operand: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "UnaryOp" and site.operator_kind() in _UNARY_OPS

    @classmethod
    def new(cls, site, ctx) -> "UnaryOpSugar":
        # Operand is factory-built (audited), never reduced here.
        return cls(
            op=site.operator_kind(),
            operand=ctx.build_body(site.unaryop_operand(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Unary result feeds the if-face; truthful rides z, lying asserts 0.
        prefix = (
            "def A(z):\n"
            "    if -2 + 3 == 1:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="unary_op_return",
            owner_sugar="UnaryOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.operand.reduce(ctx).and_then(lambda value: self._apply(value))

    def _apply(self, value) -> Outcome:
        if self.op == "Not":
            # Python `not x`: ask truth, then flip the standing.
            return value.truth(self.site).and_then(lambda standing: standing.negate())
        if self.op == "USub":
            return value.unary_minus(self.site)
        if self.op == "UAdd":
            return value.unary_plus(self.site)
        if self.op == "Invert":
            return value.bitwise_invert(self.site)
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        factory_panic(
            FactoryGapInfo(
                owner="UnaryOpSugar",
                blame=str(self.site),
                observed=self.op,
                requested="known unary op",
                fix="extend UnaryOpSugar._apply for this operator",
                gap_kind=GapKind.SUGAR,
                gap_locus=GapLocus.AST,
            ),
            FactoryAuditRow(
                role="term",
                status=FactoryAuditStatus.SUGAR_GAP,
                observed=self.op,
                blame=str(self.site),
                selected=None,
                candidates=[],
                message=f"unowned unary op {self.op}",
            ),
        )

    def walk_children(self):
        return (self.operand,)
