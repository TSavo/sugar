from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, ClassVar, NoReturn

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
    PredicateValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import ctor, eq, ne, num, str_const
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext

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
_MAX_LITERAL_REPEAT_ITEMS = 1024


@dataclass(frozen=True)
class BinaryOperatorOperation:
    method_name: ClassVar[str] = "binary_operator_with"
    operator: str
    right: FloorValue
    owner: str = "BinOpSugar"
    blame: str = "<unknown>"

    def binary_term(
        self, receiver: TermValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
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
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

        if isinstance(self.right, OpaqueOpCallsite):
            return self._emit_symbolic(receiver, self.right._downstream())
        if isinstance(self.right, CallSiteValue):
            return self._emit_symbolic(receiver, SymbolicValue(self.right.term))
        if isinstance(self.right, ObjectValue):
            return self._reflect_binary(receiver, self.right, ctx)
        self._floor_gap(receiver="TermValue")

    def binary_symbolic(
        self, receiver: SymbolicValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

        right = self.right
        if isinstance(right, OpaqueOpCallsite):
            # OpaqueOp participates as its coordinate term (or computed value).
            right = right._downstream()
        if isinstance(right, CallSiteValue):
            # Undiggable / undemanded callsite right: participate as its bridge
            # term (same coordinate surface as left-side CallSiteValue dig
            # fallback). Never invent a folded value for the callsite body.
            right = SymbolicValue(right.term)
        if isinstance(right, (TermValue, SymbolicValue)):
            return self._emit_symbolic(receiver, right)
        if isinstance(self.right, StringValue) and self.operator in {"==", "!="}:
            formula = (
                eq(receiver.term, str_const(self.right.value))
                if self.operator == "=="
                else ne(receiver.term, str_const(self.right.value))
            )
            return Complete(PredicateValue(formula))
        if isinstance(self.right, StringValue) and self.operator == "+":
            return self._symbolic_string_concat_effect()
        if isinstance(self.right, StringValue):
            return self._symbolic_string_operator_effect()
        self._floor_gap(receiver="SymbolicValue")

    def binary_string(
        self, receiver: StringValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

        # OpaqueOp (e.g. str(x) → call:str(...)) participates via its folded
        # value when counted, else as a symbolic coordinate — never invent a
        # string payload for an opaque op.
        right = self.right
        if isinstance(right, OpaqueOpCallsite):
            right = right._downstream()
        if self.operator == "+" and isinstance(right, StringValue):
            return Complete(StringValue(receiver.value + right.value))
        if self.operator == "*" and isinstance(right, TermValue):
            return self._repeat_string(receiver, right)
        if self.operator == "*" and isinstance(right, SymbolicValue):
            return self._symbolic_sequence_repeat_effect(receiver="StringValue")
        if self.operator == "+" and isinstance(right, SymbolicValue):
            return self._symbolic_string_concat_effect(
                observed=(
                    "StringValue + OpaqueOpCallsite"
                    if isinstance(self.right, OpaqueOpCallsite)
                    else "StringValue + SymbolicValue"
                ),
                carrier="right operand's runtime __radd__ carrier",
            )
        if isinstance(right, StringValue) and self.operator in {"==", "!="}:
            equal = receiver.value == right.value
            return Complete(BoolValue(equal if self.operator == "==" else not equal))
        self._floor_gap(receiver="StringValue")

    def binary_array(
        self, receiver: ArrayLiteral, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        if self.operator == "+" and isinstance(self.right, ArrayLiteral):
            return Complete(ArrayLiteral(receiver.items + self.right.items))
        if self.operator == "*" and isinstance(self.right, TermValue):
            return self._repeat_array(receiver, self.right)
        if self.operator == "*" and isinstance(self.right, SymbolicValue):
            return self._symbolic_sequence_repeat_effect(receiver="ArrayLiteral")
        self._floor_gap(receiver="ArrayLiteral")

    def binary_tuple(
        self, receiver: TupleLiteralValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        if self.operator == "*" and isinstance(self.right, TermValue):
            return self._repeat_tuple(receiver, self.right)
        if self.operator == "*" and isinstance(self.right, SymbolicValue):
            return self._symbolic_sequence_repeat_effect(receiver="TupleLiteralValue")
        self._floor_gap(receiver="TupleLiteralValue")

    def binary_encoded_string(
        self, receiver: EncodedStringValue, ctx: FactoryBuildContext | None
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
        left_term = _operand_term(left)
        right_term = _operand_term(right)
        if left_term is None or right_term is None:
            bad = left if left_term is None else right
            return Incomplete(
                FactoryGapEffect(
                    owner=self.owner,
                    blame=self.blame,
                    observed=f"{type(bad).__name__}{self.operator}symbolic operand",
                    requested="integer ProofIR term operand",
                    fix=(
                        "add a Real-sorted binary term boundary before emitting "
                        "symbolic operations over non-int concrete operands"
                    ),
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            )
        return Complete(SymbolicValue(ctor(self.operator, [left_term, right_term])))

    def _reflect_binary(
        self,
        left: FloorValue,
        right: FloorValue,
        ctx: FactoryBuildContext | None,
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
        if _repeated_item_count(len(value.items), repeat) > _MAX_LITERAL_REPEAT_ITEMS:
            return self._oversized_repeat_effect(
                receiver="ArrayLiteral",
                item_count=len(value.items),
                repeat=repeat,
            )
        return Complete(ArrayLiteral(value.items * repeat))

    def _repeat_tuple(self, value: TupleLiteralValue, count: TermValue) -> Outcome:
        repeat = self._repeat_count(count)
        if repeat is None:
            return self._repeat_count_effect(count)
        if _repeated_item_count(len(value.items), repeat) > _MAX_LITERAL_REPEAT_ITEMS:
            return self._oversized_repeat_effect(
                receiver="TupleLiteralValue",
                item_count=len(value.items),
                repeat=repeat,
            )
        return Complete(TupleLiteralValue(value.items * repeat))

    def _repeat_string(self, value: StringValue, count: TermValue) -> Outcome:
        repeat = self._repeat_count(count)
        if repeat is None:
            return self._repeat_count_effect(count)
        if _repeated_item_count(len(value.value), repeat) > _MAX_LITERAL_REPEAT_ITEMS:
            return self._oversized_repeat_effect(
                receiver="StringValue",
                item_count=len(value.value),
                repeat=repeat,
            )
        return Complete(StringValue(value.value * repeat))

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

    def _oversized_repeat_effect(
        self, *, receiver: str, item_count: int, repeat: int
    ) -> Outcome:
        return Incomplete(
            RuntimeEffect(
                "sequence repetition construction boundary: "
                f"{receiver} with {item_count} item(s) repeated {repeat} time(s) "
                f"would materialize {_repeated_item_count(item_count, repeat)} "
                "literal floor items; keep as typed red until a compact repeated-"
                f"sequence floor owns this shape. blame={self.blame}"
            )
        )

    def _symbolic_sequence_repeat_effect(self, *, receiver: str) -> Outcome:
        return Incomplete(
            RuntimeEffect(
                "sequence repetition by symbolic count: "
                f"{receiver} * SymbolicValue depends on runtime __index__/length "
                "semantics; keep as typed red until a compact symbolic repeated-"
                f"sequence floor owns this shape. blame={self.blame}"
            )
        )

    def _symbolic_string_concat_effect(
        self,
        *,
        observed: str = "SymbolicValue + StringValue",
        carrier: str = "receiver's runtime __add__ carrier",
    ) -> Outcome:
        return Incomplete(
            RuntimeEffect(
                "symbolic string concatenation runtime boundary: "
                f"{observed} depends on the {carrier} and the string-concat universe bridge is not "
                "proof-bearing yet; keep as typed red until a cited String-sorted "
                f"concat floor owns this shape. blame={self.blame}"
            )
        )

    def _symbolic_string_operator_effect(self) -> Outcome:
        return Incomplete(
            RuntimeEffect(
                "symbolic arithmetic-operator over string runtime boundary: "
                f"SymbolicValue {self.operator} StringValue has no Python numeric "
                "operator overload for str; CPython raises TypeError at runtime "
                "for every operator here except `==`/`!=`/`+`, which reduce "
                "elsewhere; keep as typed red until a cited numeric-over-string "
                f"floor owns this operator shape. blame={self.blame}"
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
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

    if isinstance(value, OpaqueOpCallsite):
        return value.to_term(owner="binary_operand")
    if isinstance(value, SymbolicValue):
        return value.term
    if (
        isinstance(value, TermValue)
        and isinstance(value.value, int)
        and not isinstance(value.value, bool)
    ):
        return num(value.value)
    return None


def _repeated_item_count(item_count: int, repeat: int) -> int:
    return item_count * max(repeat, 0)
