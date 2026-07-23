from __future__ import annotations

from dataclasses import dataclass
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

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(self.body, (SugarBody, Sugar)):
            raise TypeError("ObjectMethodValue body must be constructor-built")
