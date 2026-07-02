from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class MethodCallOperation:
    method_name: ClassVar[str] = "call_method_with"
    name: str
    arguments: tuple[FloorValue, ...]
    owner: str = "CallSugar"
    blame: str = "<unknown>"
