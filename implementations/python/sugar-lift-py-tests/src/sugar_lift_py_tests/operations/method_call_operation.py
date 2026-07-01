from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class MethodCallOperation:
    name: str
    arguments: tuple[FloorValue, ...]
    owner: str = "CallSugar"
    blame: str = "<unknown>"
