from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionCauseValue(FloorValue):
    """A statically constructed value legal in Python's ``raise ... from``."""

    value: FloorValue
    site: object = dataclass_field(compare=False)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)
