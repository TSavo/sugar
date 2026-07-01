from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Outcome

_BITWISE_OPERATORS = frozenset({"&", "|", "^", "<<", ">>"})


@dataclass(frozen=True)
class InplaceBinaryOperatorOperation:
    operator: str
    right: FloorValue
    owner: str = "AugAssignSugar"
    blame: str = "<unknown>"

    def inplace_default(self, receiver: FloorValue, ctx: object) -> Outcome:
        from sugar_lift_py_tests.operations.binary_operator_operation import (
            BinaryOperatorOperation,
        )
        from sugar_lift_py_tests.operations.bitwise_operation import BitwiseOperation
        from sugar_lift_py_tests.operations.perform_operation import perform_operation

        if self.operator in _BITWISE_OPERATORS:
            return perform_operation(
                owner=self.owner,
                blame=self.blame,
                receiver=receiver,
                method_name="bitwise_with",
                operation=BitwiseOperation(
                    operator=self.operator,
                    operand=self.right,
                    owner=self.owner,
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=receiver,
            method_name="binary_operator_with",
            operation=BinaryOperatorOperation(
                operator=self.operator,
                right=self.right,
                owner=self.owner,
                blame=self.blame,
            ),
            ctx=ctx,
        )
