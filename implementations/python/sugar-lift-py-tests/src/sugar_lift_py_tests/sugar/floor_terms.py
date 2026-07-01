from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    Bv32Value,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import Term, bool_const, ctor, num, str_const


def floor_to_term(value: Any, *, owner: str) -> Term:
    if isinstance(value, TermValue):
        return num(value.value)
    if isinstance(value, BoolValue):
        return bool_const(value.value)
    if isinstance(value, StringValue):
        return str_const(value.value)
    if isinstance(value, (SymbolicValue, Bv32Value)):
        return value.term
    if isinstance(value, ArrayLiteral):
        return ctor("array", [floor_to_term(item, owner=owner) for item in value.items])
    if isinstance(value, TupleLiteralValue):
        return ctor("tuple", [floor_to_term(item, owner=owner) for item in value.items])
    if isinstance(value, SliceValue):
        return ctor(
            "py.slice",
            [
                _optional_slice_term(value.lower, owner=owner),
                _optional_slice_term(value.upper, owner=owner),
                _optional_slice_term(value.step, owner=owner),
            ],
        )
    raise TypeError(
        f"write more Floor for {owner}: `{type(value).__name__}` cannot project to a term"
    )


def _optional_slice_term(value: Any, *, owner: str) -> Term:
    if value is None:
        return ctor("None", [])
    return floor_to_term(value, owner=owner)
