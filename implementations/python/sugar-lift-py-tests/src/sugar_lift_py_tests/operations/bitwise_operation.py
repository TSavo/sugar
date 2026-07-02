from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import (
    Bv32Value,
    FloorValue,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import Term, bvand, bvlshr, bvor, bvshl, bvxor, num
from sugar_lift_py_tests.outcome import Complete, Outcome

_BITWISE_TERMS: dict[str, Callable[[Term, Term], Term]] = {
    "&": bvand,
    "|": bvor,
    "^": bvxor,
    "<<": bvshl,
    ">>": bvlshr,
}


@dataclass(frozen=True)
class BitwiseOperation:
    operator: str
    operand: FloorValue
    owner: str = "BitwiseOpSugar"
    blame: str = "<unknown>"

    def bitwise_term(self, receiver: TermValue, ctx: object) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        return self._complete(_bv32_term(receiver))

    def bitwise_bv32(self, receiver: Bv32Value, ctx: object) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        return self._complete(receiver.term)

    def bitwise_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        return self._complete(receiver.term)

    def _reflect_bitwise(self, left: FloorValue, ctx: object) -> Outcome:
        from sugar_lift_py_tests.operations.perform_operation import perform_operation
        from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
            ReflectedBinaryOperatorOperation,
        )

        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=self.operand,
            method_name="reflected_binary_operator_with",
            operation=ReflectedBinaryOperatorOperation(
                operator=self.operator,
                left=left,
                owner=self.owner,
                blame=self.blame,
            ),
            ctx=ctx,
        )

    def _complete(self, left: Term) -> Outcome:
        builder = _BITWISE_TERMS.get(self.operator)
        if builder is None:
            raise TypeError(
                f"write more Sugar for BitwiseOpSugar operator `{self.operator}`"
            )
        return Complete(Bv32Value(builder(left, self._operand_term())))

    def _operand_term(self) -> Term:
        try:
            return _bv32_term(self.operand)
        except TypeError:
            observed = type(self.operand).__name__
            info = FactoryGapInfo(
                owner=self.owner,
                blame=self.blame,
                observed=f"operand {observed}",
                requested="bitwise operand floor",
                fix=(
                    "add BitwiseOperation support for "
                    f"{observed} or emit a real effect"
                ),
                gap_kind="Floor",
                gap_locus="construction",
            )
            raise FactoryGap(
                info,
                FactoryAuditRow(
                    role="bitwise operand floor",
                    status="floor-gap",
                    observed=info.observed,
                    blame=self.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            ) from None


def _bv32_term(value: FloorValue) -> Term:
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, SymbolicValue):
        return value.term
    if isinstance(value, TermValue):
        return num(int(value.value))
    raise TypeError(type(value).__name__)
