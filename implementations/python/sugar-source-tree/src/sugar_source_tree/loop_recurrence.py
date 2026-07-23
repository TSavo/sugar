"""Runtime projection of a validated ``LoopConstructionV1`` recurrence."""

from __future__ import annotations

from collections.abc import Mapping

from sugar_lift_py_tests.loop_construction import (
    LoopConstructionV1,
    decode_loop_construction_v1,
)

from .binding_provenance import BindingCoordinateV1
from .binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
)


def project_loop_post_binding(
    *,
    construction: LoopConstructionV1,
    binding_coordinate: BindingCoordinateV1,
    runtime_states: Mapping[str, tuple[BindingEntryV1, ...]],
    live_guards: Mapping[str, object] | None = None,
) -> LoopProjectedBinding:
    """Project one coordinate through every exact completed loop face.

    ``construction`` has already passed the closed LoopConstructionV1 decoder;
    this function only joins its sealed state identities to the live temporal
    states from the same construction traversal. A CID selects testimony but is
    never decoded or reinterpreted as a runtime value.
    """

    if not isinstance(construction, LoopConstructionV1):
        raise BindingStateWireGap("loop projection requires LoopConstructionV1")
    construction = decode_loop_construction_v1(construction.wire_graph())
    target_cid = construction.target.target_cid
    records = {
        record["completedFaceCid"]: record
        for record in construction.wire_graph()["records"]
        if record.get("kind") == "loop-completed-face"
    }
    post_face_cids = {
        record["completedFaceCid"]
        for record in construction.wire_graph()["records"]
        if record.get("kind") == "loop-post-binding"
        and record["bindingCoordinateCid"] == binding_coordinate.cid
    }
    projected_faces = []
    for face in construction.completed_faces:
        if face.cid not in post_face_cids:
            continue
        record = records.get(face.cid)
        if record is None:
            raise BindingStateWireGap("completed face missing from loop graph")
        if record["targetCid"] != target_cid:
            raise BindingStateWireGap("loop projected binding target mismatch")
        state_cid = record["stateCid"]
        snapshot = runtime_states.get(state_cid)
        if snapshot is None:
            raise BindingStateWireGap(
                f"completed face {face.cid} has no authenticated runtime state"
            )
        matches = [
            entry for entry in snapshot if entry.coordinate.cid == binding_coordinate.cid
        ]
        if len(matches) != 1:
            raise BindingStateWireGap(
                f"completed face {face.cid} has {len(matches)} entries for binding coordinate"
            )
        projected_faces.append(
            LoopProjectedCompletedFace(
                target_cid=target_cid,
                completion_kind=face.completion_kind,
                guard_formula_cid=record["guardFormulaCid"],
                state=matches[0].state,
                guard_formula=(
                    None
                    if live_guards is None
                    else live_guards.get(record["guardFormulaCid"])
                ),
            )
        )
    return LoopProjectedBinding(target_cid, tuple(projected_faces))


__all__ = ["project_loop_post_binding"]
