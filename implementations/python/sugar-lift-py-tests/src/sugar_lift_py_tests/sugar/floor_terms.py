from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    Bv32Value,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import Term, ctor, num, str_const


def floor_to_term(value: Any, *, owner: str) -> Term:
    if isinstance(value, TermValue):
        return num(value.value)
    if isinstance(value, StringValue):
        return str_const(value.value)
    if isinstance(value, (SymbolicValue, Bv32Value)):
        return value.term
    if isinstance(value, ArrayLiteral):
        return ctor("array", [floor_to_term(item, owner=owner) for item in value.items])
    raise TypeError(
        f"write more Floor for {owner}: `{type(value).__name__}` cannot project to a term"
    )
