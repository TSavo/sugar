from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    FloorValue,
    ObjectValue,
    TermValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class DelItemOperation:
    method_name: ClassVar[str] = "delitem_with"
    index: FloorValue
    owner: str = "SubscriptDeleteSugar"
    blame: str = "<unknown>"

    def delitem_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        index = _concrete_sequence_index(
            self.index,
            ctx,
            length=len(receiver.items),
            owner=f"{self.owner} array index",
        )
        if index is None:
            return Incomplete(
                RuntimeEffect(
                    "subscript delete runtime boundary: list deletion requires a "
                    "concrete in-bounds integer index; Python checks dynamic "
                    "indices and raises IndexError at runtime. Keep as typed red "
                    "until a narrower mutation floor owns this shape. "
                    f"blame={self.blame}"
                )
            )
        return Complete(
            ArrayLiteral((*receiver.items[:index], *receiver.items[index + 1 :]))
        )

    def delitem_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__delitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
        )


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
