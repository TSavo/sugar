from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_string_subscript_sugar
from sugar_lift_py_tests.floor import Bv32Value, EncodedStringValue, StringValue, TermValue
from sugar_lift_py_tests.ir import Term, num
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class StringSubscriptSugar:
    """`table[index]` -- index a string-valued receiver by a BV term.

    The receiver reduces to the constant table; the index reduces to a BV term.
    The result is one output character: table[index]. Composed under `+`
    (BinOpSugar) it grows into the full encoded string. No value is computed --
    the (table, index-term) pair IS the per-character constraint."""

    receiver: SugarBody
    index: SugarBody

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("StringSubscriptSugar receiver must be factory-built")
        if not isinstance(self.index, SugarBody):
            raise TypeError("StringSubscriptSugar index must be factory-built")

    @classmethod
    def from_site(
        cls, site, *, receiver: SugarBody, index: SugarBody
    ) -> "StringSubscriptSugar | None":
        if site.observed != "Subscript":
            return None
        return cls(receiver=receiver, index=index)

    def desugar(self, ctx=None) -> Outcome:
        receiver = complete_value(self.receiver.reduce(ctx), owner="StringSubscriptSugar receiver")
        if not isinstance(receiver, StringValue):
            raise TypeError(
                "write more Floor for StringSubscriptSugar receiver: expected StringValue "
                f"got {type(receiver).__name__}"
            )
        index = complete_value(self.index.reduce(ctx), owner="StringSubscriptSugar index")
        return Complete(
            EncodedStringValue(
                table=tuple(ord(ch) for ch in receiver.value),
                indices=(_bv_term(index),),
            )
        )


def _bv_term(value) -> Term:
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(value.value)
    raise TypeError(
        f"write more Floor for StringSubscriptSugar index `{type(value).__name__}`: "
        "expected TermValue or Bv32Value"
    )


def _owns(site) -> bool:
    return site.observed == "Subscript"


STRING_SUBSCRIPT_CLAIM = SugarClaim(
    name="StringSubscriptSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_string_subscript_sugar,
)
