from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, ClassVar

from sugar_lift_py_tests.factory import (
    FactoryAuditRow, factory_panic,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import (
    Bv32Value,
    FloorValue,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import Term, bvand, bvlshr, bvor, bvshl, bvxor, num
from sugar_lift_py_tests.outcome import Complete, Outcome

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext

_BITWISE_TERMS: dict[str, Callable[[Term, Term], Term]] = {
    "&": bvand,
    "|": bvor,
    "^": bvxor,
    "<<": bvshl,
    ">>": bvlshr,
}

_BITWISE_FOLDS: dict[str, Callable[[int, int], int]] = {
    "&": lambda left, right: left & right,
    "|": lambda left, right: left | right,
    "^": lambda left, right: left ^ right,
    "<<": lambda left, right: left << right,
    ">>": lambda left, right: left >> right,
}


@dataclass(frozen=True)
class BitwiseOperation:
    method_name: ClassVar[str] = "bitwise_with"
    operator: str
    operand: FloorValue
    owner: str = "BitwiseOpSugar"
    blame: str = "<unknown>"

    def bitwise_term(
        self, receiver: TermValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        folded = self._fold_concrete_ints(receiver)
        if folded is not None:
            return Complete(TermValue(folded))
        return self._complete(_bv32_term(receiver))

    def bitwise_bv32(
        self, receiver: Bv32Value, ctx: FactoryBuildContext | None
    ) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        return self._complete(receiver.term)

    def bitwise_symbolic(
        self, receiver: SymbolicValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        if isinstance(self.operand, ObjectValue):
            return self._reflect_bitwise(receiver, ctx)
        return self._complete(receiver.term)

    def _reflect_bitwise(
        self, left: FloorValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        from sugar_lift_py_tests.operations.perform_operation import perform_operation
        from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
            ReflectedBinaryOperatorOperation,
        )

        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=self.operand,
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
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
            factory_panic(
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
            )

    def _fold_concrete_ints(self, receiver: TermValue) -> int | None:
        left = _concrete_int(receiver)
        right = _concrete_int(self.operand)
        if left is None or right is None:
            return None
        folder = _BITWISE_FOLDS.get(self.operator)
        if folder is None:
            return None
        try:
            return folder(left, right)
        except ValueError:
            return None


def _bv32_term(value: FloorValue) -> Term:
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, SymbolicValue):
        return value.term
    if isinstance(value, TermValue):
        return num(int(value.value))
    raise TypeError(type(value).__name__)


def _concrete_int(value: FloorValue) -> int | None:
    if not isinstance(value, TermValue):
        return None
    # bool is an int subclass in Python, but the bitwise witness here is the
    # vendor's integer operator. Bool-valued bitwise semantics stay on their
    # existing non-folding path until a bool-specific witness owns them.
    if isinstance(value.value, bool) or not isinstance(value.value, int):
        return None
    return value.value
