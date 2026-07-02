from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SliceValue(FloorValue):
    lower: FloorValue | None
    upper: FloorValue | None
    step: FloorValue | None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "py.slice",
            [
                _optional_slice_term(self.lower, owner=owner),
                _optional_slice_term(self.upper, owner=owner),
                _optional_slice_term(self.step, owner=owner),
            ],
        )


def _optional_slice_term(value: FloorValue | None, *, owner: str):
    from sugar_lift_py_tests.ir import ctor

    if value is None:
        return ctor("None", [])
    return value.to_term(owner=owner)
