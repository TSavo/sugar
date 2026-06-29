from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedReturn(FloorValue):
    """A return reached only under a guard -- a branch's return. `guards` is the
    conjunction of `if` conditions on the way to it (an else branch negates its
    test). When a body becomes a universe, a GuardedReturn lowers to
    `implies(and(guards), out == value)`. An unguarded return is a ReturnValue."""

    guards: tuple
    value: object
