from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class ReflectedBinaryOperatorOperation:
    method_name: ClassVar[str] = "reflected_binary_operator_with"
    operator: str
    left: FloorValue
    owner: str = "BinOpSugar"
    blame: str = "<unknown>"
