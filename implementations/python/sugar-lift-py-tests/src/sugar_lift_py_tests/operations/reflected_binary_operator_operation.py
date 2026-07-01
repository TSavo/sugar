from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class ReflectedBinaryOperatorOperation:
    operator: str
    left: FloorValue
    owner: str = "BinOpSugar"
    blame: str = "<unknown>"
