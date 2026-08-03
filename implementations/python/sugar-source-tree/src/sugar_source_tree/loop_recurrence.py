"""Runtime projection of a validated ``LoopConstructionV1`` recurrence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sugar_lift_python_source.canonical import cid_of_json

from sugar_lift_py_tests.loop_construction import (
    LoopConstructionV1,
    decode_loop_construction_v1,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

from .binding_provenance import BindingCoordinateV1
from .binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
)

_PRODUCT_MINT_AUTHORITY = cid_of_json(
    {"owner": "sugar_source_tree.loop_recurrence.project_loop_post_binding"}
)


@dataclass(frozen=True)
class LoopProjectedBindingProductSugar(ConstructedTermSugar):
    """Closed term product minted with one authenticated loop projection."""

    name: str
    projection: object
    site: object
    binding_coordinate: BindingCoordinateV1
    target_cid: str
    name_identity_cid: str
    occurrence_cid: str
    _mint_authority: object

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.binding_projection import LoopGuardedProjection

        if self._mint_authority is not _PRODUCT_MINT_AUTHORITY:
            raise BindingStateWireGap(
                "loop binding product must come from its authenticated projection mint"
            )
        if not isinstance(self.projection, LoopGuardedProjection):
            raise BindingStateWireGap(
                "loop binding product requires the producer's exact projection"
            )
        if self.projection.target_cid != self.target_cid:
            raise BindingStateWireGap(
                "loop binding product has a foreign loop occurrence"
            )
        if cid_of_json(self.binding_coordinate.preimage) != self.binding_coordinate.cid:
            raise BindingStateWireGap("loop binding product has a foreign coordinate")
        expected_name = cid_of_json(
            {
                "bindingCoordinateCid": self.binding_coordinate.cid,
                "name": self.name,
            }
        )
        if self.name_identity_cid != expected_name:
            raise BindingStateWireGap("loop binding product has a foreign binding name")
        expected_occurrence = cid_of_json(self.site.seal().to_dict())
        if self.occurrence_cid != expected_occurrence:
            raise BindingStateWireGap(
                "loop binding product has a foreign read occurrence"
            )
        if (
            self.binding_coordinate.binding_site["source_cid"]
            != self.site.seal().source_cid
        ):
            raise BindingStateWireGap("loop binding product crosses source frames")

    @classmethod
    def _mint(
        cls,
        *,
        name: str,
        projection: object,
        site: object,
        binding_coordinate: BindingCoordinateV1,
        target_cid: str,
    ) -> "LoopProjectedBindingProductSugar":
        return cls(
            name,
            projection,
            site,
            binding_coordinate,
            target_cid,
            cid_of_json({"bindingCoordinateCid": binding_coordinate.cid, "name": name}),
            cid_of_json(site.seal().to_dict()),
            _PRODUCT_MINT_AUTHORITY,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding

        return read_binding(
            self.projection, read_name=self.name, read_site=self.site, ctx=ctx
        ).collapse()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
            GuardedBindingReadSugar,
        )

        return GuardedBindingReadSugar(
            name=self.name, state=self.projection, site=self.site
        ).to_term(owner=owner)


def project_loop_post_binding(
    *,
    construction: LoopConstructionV1,
    binding_coordinate: BindingCoordinateV1,
    runtime_states: Mapping[str, tuple[BindingEntryV1, ...]],
    live_guards: Mapping[str, object] | None = None,
    read_name: str | None = None,
    read_site: object | None = None,
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
    post_records = [
        record
        for record in construction.wire_graph()["records"]
        if record.get("kind") == "loop-post-binding"
        and record["bindingCoordinateCid"] == binding_coordinate.cid
    ]
    post_face_cids = {record["completedFaceCid"] for record in post_records}
    if len(post_face_cids) != len(post_records):
        raise BindingStateWireGap(
            "loop post-binding projection repeats one completed route"
        )
    # The DECLARED size of this loop occurrence's exit family. Read off the
    # producer's own records, never counted from what arrived: counting would
    # make a dropped face silently re-read as a smaller complete partition,
    # which is precisely the "partial partition certified exhaustive" failure
    # the admission rule in `outcome/exit_set.py` exists to refuse.
    declared = {record["exitPartitionArity"] for record in post_records}
    if len(declared) > 1:
        raise BindingStateWireGap(
            "loop post-binding records disagree on exitPartitionArity for one "
            f"binding coordinate: observed {sorted(declared)}"
        )
    exit_partition_arity = declared.pop() if declared else None
    completed_by_cid = {face.cid: face for face in construction.completed_faces}
    projected_faces = []
    for post_record in post_records:
        face_cid = post_record["completedFaceCid"]
        face = completed_by_cid.get(face_cid)
        if face is None:
            raise BindingStateWireGap("post-binding face missing from loop graph")
        record = records.get(face_cid)
        if record is None:
            raise BindingStateWireGap("completed face missing from loop graph")
        if record["targetCid"] != target_cid:
            raise BindingStateWireGap("loop projected binding target mismatch")
        state_cid = record["stateCid"]
        if post_record["projectedStateCid"] != state_cid:
            raise BindingStateWireGap(
                "loop post-binding projected state does not match completed route"
            )
        snapshot = runtime_states.get(state_cid)
        if snapshot is None:
            raise BindingStateWireGap(
                f"completed face {face.cid} has no authenticated runtime state"
            )
        matches = [
            entry
            for entry in snapshot
            if entry.coordinate.cid == binding_coordinate.cid
        ]
        if len(matches) != 1:
            raise BindingStateWireGap(
                f"completed face {face.cid} has {len(matches)} entries for binding coordinate"
            )
        live_guard = (
            None if live_guards is None else live_guards.get(record["guardFormulaCid"])
        )
        if live_guards is not None:
            if live_guard is None:
                raise BindingStateWireGap(
                    "completed face has no authenticated live guard formula"
                )
            from .live_loop_construction import _formula_cid

            if _formula_cid(live_guard) != record["guardFormulaCid"]:
                raise BindingStateWireGap(
                    "completed face live guard formula does not match producer testimony"
                )
        projected_faces.append(
            LoopProjectedCompletedFace(
                target_cid=target_cid,
                completion_kind=face.completion_kind,
                guard_formula_cid=record["guardFormulaCid"],
                state=matches[0].state,
                guard_formula=live_guard,
                exit_partition_arity=exit_partition_arity,
            )
        )
    if exit_partition_arity is not None and len(projected_faces) != (
        exit_partition_arity
    ):
        raise BindingStateWireGap(
            "loop exit partition is short of its declared size: the producer "
            f"declared {exit_partition_arity} exit routes and this projection "
            f"retained {len(projected_faces)}. A partition missing a face is "
            "an outcome nobody accounted for; do not project it as complete"
        )
    faces = tuple(projected_faces)
    if read_name is None or read_site is None:
        return LoopProjectedBinding(target_cid, faces)
    from .nodes import _construct_binding_projection

    provisional = LoopProjectedBinding(target_cid, faces)
    projection = _construct_binding_projection(provisional)
    product = LoopProjectedBindingProductSugar._mint(
        name=read_name,
        projection=projection,
        site=read_site,
        binding_coordinate=binding_coordinate,
        target_cid=target_cid,
    )
    return LoopProjectedBinding(target_cid, faces, projection, product)


__all__ = ["LoopProjectedBindingProductSugar", "project_loop_post_binding"]
