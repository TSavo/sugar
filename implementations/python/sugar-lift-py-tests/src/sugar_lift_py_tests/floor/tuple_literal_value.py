from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TupleLiteralValue(FloorValue):
    items: tuple[FloorValue, ...]

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleLiteralValue.setitem"
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleLiteralValue.delitem"
        )

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="TupleLiteralValue.setattr",
        )

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="TupleLiteralValue.delattr",
        )

    def __post_init__(self) -> None:
        if not all(isinstance(item, FloorValue) for item in self.items):
            raise TypeError("TupleLiteralValue items must be floor values")

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("tuple", [item.to_term(owner=owner) for item in self.items])

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_tuple(self, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_tuple(self, ctx)
