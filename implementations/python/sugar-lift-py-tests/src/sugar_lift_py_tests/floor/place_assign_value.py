from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class PlaceAssignValue(FloorValue):
    receiver: FloorValue
    selector_kind: str
    selector: object
    value: FloorValue

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.selector_kind != "attribute":
            raise ValueError(f"unknown place selector kind {self.selector_kind!r}")
        receiver = self.receiver.to_term(owner=owner)
        target = ctor(
            "python:attribute",
            [receiver, str_const(self.selector)],
        )
        return ctor(
            "python:assign",
            [target, self.value.to_term(owner=owner)],
        )
