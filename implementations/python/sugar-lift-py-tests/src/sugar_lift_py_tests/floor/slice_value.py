from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SliceValue(FloorValue):
    lower: FloorValue | None
    upper: FloorValue | None
    step: FloorValue | None

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SliceValue.setitem"
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SliceValue.delitem"
        )

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
