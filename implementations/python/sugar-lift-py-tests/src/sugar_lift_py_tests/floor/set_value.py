from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SetValue(FloorValue):
    """A set of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this set does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple
