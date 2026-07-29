from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sugar_lift_py_tests.sugar_body import SugarBody

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

from .floor_value import FloorValue


@dataclass(frozen=True)
class ObjectMethodValue(FloorValue):
    name: str
    parameters: tuple[str, ...]
    # build_body returns SugarBody[Any] (FactoryBuildContext.build_body); Any
    # is the open membrane here, matching FactoryBuildResult.sugar, since a
    # method body's reduction shape varies with the SugarRole it was built
    # under and is not known at this seam.
    body: SugarBody[Any] | Sugar
    source_call_frame_cid: str | None = None
    formal_coordinate_cids: tuple[str, ...] = ()
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    descriptor_kind: str | None = None

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(self.body, (SugarBody, Sugar)):
            raise TypeError("ObjectMethodValue body must be constructor-built")

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.setitem",
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.delitem",
        )

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="ObjectMethodValue.setattr",
        )

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="ObjectMethodValue.delattr",
        )
