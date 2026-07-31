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
    # build_body returns SugarBody[Any]; Any
    # is the open membrane here, matching FactoryBuildResult.sugar, since a
    # method body's reduction shape varies with the SugarRole it was built
    # under and is not known at this seam.
    body: SugarBody[Any] | Sugar
    source_call_frame_cid: str | None = None
    formal_coordinate_cids: tuple[str, ...] = ()
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    descriptor_kind: str | None = None
    # Exact lexical owner of this method body.  Inherited methods retain their
    # defining class rather than being rebound to the runtime receiver class;
    # this is the authenticated ``__class__`` cell used by zero-arg super().
    defining_class: object | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(self.body, (SugarBody, Sugar)):
            raise TypeError("ObjectMethodValue body must be constructor-built")

    def to_term(self, *, owner: str):
        """Project the authenticated source-frame identity of this function."""
        del owner
        if not self.source_call_frame_cid:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ObjectMethodValue.to_term",
                blame=self.name,
                observed="method without source call frame CID",
                requested="one authenticated source method coordinate",
                fix="retain the defining source frame or keep the method loud",
            )
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:source-method-value",
            (str_const(self.source_call_frame_cid),),
            symbol_kind="coordinate",
        )

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
