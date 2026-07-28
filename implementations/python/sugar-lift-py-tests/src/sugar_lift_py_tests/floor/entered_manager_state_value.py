from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .object_value import ObjectValue


@dataclass(frozen=True)
class EnteredManagerStateValue(FloorValue):
    """One completed ``__enter__`` face and its exact receiver state."""

    enter_value: FloorValue
    receiver_state: ObjectValue

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:entered-manager-state",
            (
                self.enter_value.to_term(owner=owner),
                self.receiver_state.to_term(owner=owner),
            ),
        )
