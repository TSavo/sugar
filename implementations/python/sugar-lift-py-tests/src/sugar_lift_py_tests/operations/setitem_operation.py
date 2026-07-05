from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, TypeAlias

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    FloorValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleLiteralValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

from .object_method_call import call_object_method_value

ArrayItem: TypeAlias = (
    TermValue
    | BoolValue
    | ObjectValue
    | StringValue
    | SymbolicValue
    | ArrayLiteral
    | TupleLiteralValue
)


@dataclass(frozen=True)
class SetItemOperation:
    method_name: ClassVar[str] = "setitem_with"
    index: FloorValue
    value: FloorValue
    owner: str = "SubscriptAssignSugar"
    blame: str = "<unknown>"

    def setitem_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        index = _concrete_sequence_index(
            self.index,
            ctx,
            length=len(receiver.items),
            owner=f"{self.owner} array index",
        )
        if index is None:
            return Incomplete(
                RuntimeEffect(
                    "subscript assignment runtime boundary: list assignment "
                    "requires a concrete in-bounds integer index; Python checks "
                    "dynamic indices and raises IndexError at runtime. Keep as "
                    "typed red until a narrower mutation floor owns this shape. "
                    f"blame={self.blame}"
                )
            )
        value = _array_item(self.value)
        if value is None:
            return Incomplete(
                RuntimeEffect(
                    "subscript assignment runtime boundary: list assignment "
                    f"cannot preserve ArrayLiteral for value floor "
                    f"{type(self.value).__name__}; Python stores runtime objects "
                    "by reference. Keep as typed red until a narrower mutation "
                    f"floor owns this shape. blame={self.blame}"
                )
            )
        return Complete(
            ArrayLiteral(
                (
                    *receiver.items[:index],
                    value,
                    *receiver.items[index + 1 :],
                )
            )
        )

    def setitem_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__setitem__",
            (self.index, self.value),
            owner=self.owner,
            blame=self.blame,
        )


def _array_item(value: FloorValue) -> ArrayItem | None:
    if isinstance(
        value,
        (
            TermValue,
            BoolValue,
            ObjectValue,
            StringValue,
            SymbolicValue,
            ArrayLiteral,
            TupleLiteralValue,
        ),
    ):
        return value
    return None


def _concrete_sequence_index(
    index: FloorValue,
    ctx: object,
    *,
    length: int,
    owner: str,
) -> int | None:
    index = force_floor(index, ctx, owner=owner)
    if isinstance(index, BoolValue):
        index = TermValue(1 if index.value else 0)
    if not (isinstance(index, TermValue) and type(index.value) is int):
        return None
    resolved = index.value if index.value >= 0 else length + index.value
    if 0 <= resolved < length:
        return resolved
    return None
