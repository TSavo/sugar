"""Cut D: construct source-visible context-manager protocol methods once."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.manager_coordinate import (
    ExitTracebackCoordinate,
    ExitTypeCoordinate,
    ExitValueCoordinate,
)
from sugar_lift_py_tests.outcome import Complete

from .canonical import cid_of_json
from .manager_construction import ConstructedManagerBehaviorV1


@dataclass(frozen=True)
class ConstructedManagerProtocolV1:
    manager_construction_cid: str
    protocol_construction_cid: str
    enter_call: CallSiteValue = field(compare=False)
    exit_call: CallSiteValue = field(compare=False)
    enter_frame_cid: str
    exit_frame_cid: str
    exit_face_id: str

    @property
    def preimage(self):
        return {
            "kind": "constructed-manager-protocol",
            "schemaVersion": "1",
            "managerConstructionCid": self.manager_construction_cid,
            "enterFrameCid": self.enter_frame_cid,
            "exitFrameCid": self.exit_frame_cid,
            "exitFaceId": self.exit_face_id,
        }

    def __post_init__(self) -> None:
        if cid_of_json(self.preimage) != self.protocol_construction_cid:
            raise ValueError("manager protocol CID does not match its preimage")

    def enter_outcome(self, ctx: object = None):
        return self.enter_call.reduce_source_outcome(ctx)

    def exit_outcome(self, ctx: object = None):
        return self.exit_call.reduce_source_outcome(ctx)


@dataclass(frozen=True)
class ManagerProtocolConstructionGapV1:
    kind: Literal["enter-missing", "exit-missing", "method-construction"]
    manager_construction_cid: str
    detail: str


def construct_manager_protocol(
    behavior: ConstructedManagerBehaviorV1,
    *,
    exit_face_id: str,
) -> ConstructedManagerProtocolV1 | ManagerProtocolConstructionGapV1:
    """Project ``__enter__``/``__exit__`` from Cut C's exact receiver.

    Method bodies were constructed by ``FunctionDef`` and retained by the
    class-construction arm.  This function only binds the constructed receiver
    and the typed exit-face operands to those bodies.
    """
    receiver = behavior.receiver_state
    if not receiver.has_method("__enter__"):
        return ManagerProtocolConstructionGapV1(
            "enter-missing", behavior.manager_construction_cid, "source-visible method"
        )
    if not receiver.has_method("__exit__"):
        return ManagerProtocolConstructionGapV1(
            "exit-missing", behavior.manager_construction_cid, "source-visible method"
        )
    enter = receiver.call_method_value(
        "__enter__", (), owner="construct_manager_protocol", blame=exit_face_id
    )
    exit_ = receiver.call_method_value(
        "__exit__",
        (
            ExitTypeCoordinate(exit_face_id, None),
            ExitValueCoordinate(exit_face_id, None),
            ExitTracebackCoordinate(exit_face_id, None),
        ),
        owner="construct_manager_protocol",
        blame=exit_face_id,
    )
    if not isinstance(enter, Complete) or not isinstance(enter.value, CallSiteValue):
        return ManagerProtocolConstructionGapV1(
            "method-construction", behavior.manager_construction_cid, "__enter__"
        )
    if not isinstance(exit_, Complete) or not isinstance(exit_.value, CallSiteValue):
        return ManagerProtocolConstructionGapV1(
            "method-construction", behavior.manager_construction_cid, "__exit__"
        )
    enter_frame_cid = _method_frame_cid(receiver, "__enter__")
    exit_frame_cid = _method_frame_cid(receiver, "__exit__")
    preimage = {
        "kind": "constructed-manager-protocol",
        "schemaVersion": "1",
        "managerConstructionCid": behavior.manager_construction_cid,
        "enterFrameCid": enter_frame_cid,
        "exitFrameCid": exit_frame_cid,
        "exitFaceId": exit_face_id,
    }
    return ConstructedManagerProtocolV1(
        behavior.manager_construction_cid,
        cid_of_json(preimage),
        enter.value,
        exit_.value,
        enter_frame_cid,
        exit_frame_cid,
        exit_face_id,
    )


def _method_frame_cid(receiver, name: str) -> str:
    method = next(item for item in reversed(receiver.methods) if item.name == name)
    if method.source_call_frame_cid is None:
        raise ValueError("source-visible method has no authenticated call frame")
    return method.source_call_frame_cid
