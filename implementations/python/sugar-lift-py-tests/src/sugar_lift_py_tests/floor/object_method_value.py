from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.sugar_body import SugarBody

from .floor_value import FloorValue


@dataclass(frozen=True)
class ObjectMethodValue(FloorValue):
    name: str
    parameters: tuple[str, ...]
    body: SugarBody

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("ObjectMethodValue body must be factory-built")
