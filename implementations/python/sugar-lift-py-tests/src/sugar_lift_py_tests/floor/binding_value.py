from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BindingValue(FloorValue):
    """The outcome of an assignment: a name bound to a value. It is a SCOPE effect --
    the enclosing block threads it into the reduce context so later statements resolve
    the name (a let-binding). It is not itself a returned outcome."""

    name: str
    value: object
