from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.sugar_body import SugarBody

from .floor_value import FloorValue


@dataclass(frozen=True)
class ObjectMethodValue(FloorValue):
    name: str
    parameters: tuple[str, ...]
    # build_body returns SugarBody[Any] (FactoryBuildContext.build_body); Any
    # is the open membrane here, matching FactoryBuildResult.sugar, since a
    # method body's reduction shape varies with the SugarRole it was built
    # under and is not known at this seam.
    body: SugarBody[Any]

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("ObjectMethodValue body must be factory-built")
