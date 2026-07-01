from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import (
    EncodedStringValue,
    FloorValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

_FOLD = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "//": lambda a, b: a // b,
    "%": lambda a, b: a % b,
    "**": lambda a, b: a**b,
}

# Operators whose divisor of 0 is a runtime effect (Python raises), not a value.
_DIVIDES = {"/", "//", "%"}


@dataclass(frozen=True)
class BinaryOperatorOperation:
    operator: str
    right: FloorValue
    owner: str = "BinOpSugar"
    blame: str = "<unknown>"

    def binary_term(self, receiver: TermValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.right, TermValue):
            if self.operator in _DIVIDES and self.right.value == 0:
                return Incomplete(
                    RuntimeEffect(
                        f"division by zero (`{self.operator}` by 0): a runtime "
                        "DivByZero effect that raises and stops constraint propagation"
                    )
                )
            return Complete(
                TermValue(_FOLD[self.operator](receiver.value, self.right.value))
            )
        if isinstance(self.right, SymbolicValue):
            return self._emit_symbolic(receiver, self.right)
        self._floor_gap(receiver="TermValue")

    def binary_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.right, (TermValue, SymbolicValue)):
            return self._emit_symbolic(receiver, self.right)
        self._floor_gap(receiver="SymbolicValue")

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

    def _floor_gap(self, *, receiver: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver}{self.operator}{type(self.right).__name__}",
            requested="binary operator operand floor",
            fix=(
                f"add BinaryOperatorOperation support for {receiver} "
                f"{self.operator} {type(self.right).__name__}"
            ),
            gap_kind="Floor",
            gap_locus="construction",
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
