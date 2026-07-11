from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class DictValue(FloorValue):
    """A dict of reduced (key, value) floor pairs, in source order.

    The sugar reduces each key and each value; the floor holds what those
    reductions were. No methods -- floors this dict does not implement panic
    for free via FloorValue defaults.
    """

    entries: tuple
