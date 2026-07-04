from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ClassVar, NoReturn

from sugar_lift_py_tests.effect import FactoryGapEffect, RuntimeEffect
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    EncodedStringValue,
    FloorValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

_FOLD: dict[str, Callable[[int | float, int | float], int | float]] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "//": lambda a, b: a // b,
    "%": lambda a, b: a % b,
    "**": lambda a, b: a**b,
}

# Operators whose divisor of 0 is a runtime effect (Python raises), not a value.
_DIVIDES = {"/", "//", "%", "divmod"}


@dataclass(frozen=True)
class BinaryOperatorOperation:
    method_name: ClassVar[str] = "binary_operator_with"
    operator: str
    right: FloorValue
    owner: str = "BinOpSugar"
    blame: str = "<unknown>"

    def binary_term(self, receiver: TermValue, ctx: object) -> Outcome:
        if self.operator == "*" and isinstance(self.right, ArrayLiteral):
            return self._repeat_array(self.right, receiver)
        if self.operator == "*" and isinstance(self.right, TupleLiteralValue):
            return self._repeat_tuple(self.right, receiver)
        if isinstance(self.right, TermValue):
            if self.operator in {"==", "!="}:
                equal = receiver.value == self.right.value
                return Complete(
                    BoolValue(equal if self.operator == "==" else not equal)
                )
            if self.operator in _DIVIDES and self.right.value == 0:
                return Incomplete(
                    RuntimeEffect(
                        f"division by zero (`{self.operator}` by 0): a runtime "
                        "DivByZero effect that raises and stops constraint propagation"
                    )
                )
            if self.operator == "divmod":
                quotient, remainder = divmod(receiver.value, self.right.value)
                return Complete(
                    TupleLiteralValue(
                        (TermValue(int(quotient)), TermValue(int(remainder)))
                    )
                )
            folder = _FOLD.get(self.operator)
            if folder is None:
                self._floor_gap(receiver="TermValue")
            return Complete(TermValue(folder(receiver.value, self.right.value)))
        if isinstance(self.right, SymbolicValue):
            return self._emit_symbolic(receiver, self.right)
        if isinstance(self.right, ObjectValue):
            return self._reflect_binary(receiver, self.right, ctx)
        self._floor_gap(receiver="TermValue")

    def binary_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.right, (TermValue, SymbolicValue)):
            return self._emit_symbolic(receiver, self.right)
        self._floor_gap(receiver="SymbolicValue")

    def binary_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.right, StringValue) and self.operator in {"==", "!="}:
            equal = receiver.value == self.right.value
            return Complete(BoolValue(equal if self.operator == "==" else not equal))
        self._floor_gap(receiver="StringValue")

    def binary_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        if self.operator == "*" and isinstance(self.right, TermValue):
            return self._repeat_array(receiver, self.right)
        self._floor_gap(receiver="ArrayLiteral")

    def binary_tuple(self, receiver: TupleLiteralValue, ctx: object) -> Outcome:
        del ctx
        if self.operator == "*" and isinstance(self.right, TermValue):
            return self._repeat_tuple(receiver, self.right)
        if self.operator == "*" and isinstance(self.right, SymbolicValue):
            return self._symbolic_tuple_repeat_effect()
        self._floor_gap(receiver="TupleLiteralValue")

    def binary_encoded_string(
        self, receiver: EncodedStringValue, ctx: object
    ) -> Outcome:
        del ctx
        if not isinstance(self.right, EncodedStringValue):
            self._floor_gap(receiver="EncodedStringValue")
        if self.operator != "+":
            raise TypeError("BinOpSugar only concatenates encoded strings with +")
        if receiver.table != self.right.table:
            raise TypeError("BinOpSugar + concatenates encoded strings over one table")
        return Complete(
            EncodedStringValue(
                table=receiver.table, indices=receiver.indices + self.right.indices
            )
        )

    def _emit_symbolic(
        self, left: TermValue | SymbolicValue, right: TermValue | SymbolicValue
    ) -> Outcome:
        return Complete(
            SymbolicValue(
                ctor(self.operator, [_operand_term(left), _operand_term(right)])
            )
        )

    def _reflect_binary(
        self, left: FloorValue, right: FloorValue, ctx: object
    ) -> Outcome:
        from sugar_lift_py_tests.operations.perform_operation import perform_operation
        from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
            ReflectedBinaryOperatorOperation,
        )

        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=right,
            operation=ReflectedBinaryOperatorOperation(
                operator=self.operator,
                left=left,
                owner=self.owner,
                blame=self.blame,
            ),
            ctx=ctx,
        )

    def _repeat_array(self, value: ArrayLiteral, count: TermValue) -> Outcome:
        repeat = self._repeat_count(count)
        if repeat is None:
            return self._repeat_count_effect(count)
        return Complete(ArrayLiteral(value.items * repeat))

    def _repeat_tuple(self, value: TupleLiteralValue, count: TermValue) -> Outcome:
        repeat = self._repeat_count(count)
        if repeat is None:
            return self._repeat_count_effect(count)
        return Complete(TupleLiteralValue(value.items * repeat))

    def _repeat_count(self, count: TermValue) -> int | None:
        if isinstance(count.value, int):
            return count.value
        return None

    def _repeat_count_effect(self, count: TermValue) -> Outcome:
        return Incomplete(
            RuntimeEffect(
                "sequence repetition by non-int "
                f"({type(count.value).__name__}): a runtime TypeError effect"
            )
        )

    def _symbolic_tuple_repeat_effect(self) -> Outcome:
        return Incomplete(
            FactoryGapEffect(
                owner=self.owner,
                blame=self.blame,
                observed="TupleLiteralValue*SymbolicValue",
                requested="concrete tuple repetition count",
                fix=(
                    "only fold tuple repetition when the repeat count is a "
                    "concrete int; carry symbolic/runtime counts as a typed effect"
                ),
                gap_kind="Floor",
                gap_locus="Construction",
            )
        )

    def _floor_gap(self, *, receiver: str) -> NoReturn:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver}{self.operator}{type(self.right).__name__}",
            requested="binary operator operand floor",
            fix=(
                f"add BinaryOperatorOperation support for {receiver} "
                f"{self.operator} {type(self.right).__name__}"
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="binary operator operand floor",
                status="floor-gap",
                observed=info.observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )


def _operand_term(value: FloorValue):
    """ProofIR term for an emitted binary operand.

    Concrete floats still wait on the Real refinement when paired with symbolic
    operands; preserve the prior operator boundary instead of widening it here.
    """
    if isinstance(value, SymbolicValue):
        return value.term
    if (
        isinstance(value, TermValue)
        and isinstance(value.value, int)
        and not isinstance(value.value, bool)
    ):
        return num(value.value)
    raise TypeError(
        f"BinOpSugar cannot lift operand `{type(value).__name__}` to a term"
    )
