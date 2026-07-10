from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome
    from sugar_lift_py_tests.sugar_body import SugarBody


class BoolFloor(Protocol):
    """The bool floor is an interface: a value stands on it iff it does this one
    thing -- decide a two-way branch. Given the two faces (then, else), emit one.
    `TrueBoolLiteralSugar` returns the then, `FalseBoolLiteralSugar` returns the else;
    other values do it their own way (a string by emptiness, an int by zero-ness). A
    value that cannot do the bool thing simply does not implement this, and the base
    FloorValue's panic is the honest 'no' -- absence is the contract."""

    def binary_conditional(
        self, then: "SugarBody", else_body: "SugarBody | None", ctx: object = None
    ) -> "Outcome": ...
