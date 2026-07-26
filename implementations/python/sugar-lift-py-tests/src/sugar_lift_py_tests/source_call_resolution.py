"""Closed exact-use outcomes for authenticated source-call preconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sugar_lift_python_source.canonical import cid_of_json

from .context_manager_resolution import SourceFragmentCoordinateV1


@dataclass(frozen=True)
class SourceCallPreconstructionRefV1:
    use_site: SourceFragmentCoordinateV1
    resolved_object_cid: str
    distribution_artifact_cid: str
    source_call_frame_cid: str
    dispatch_kind: Literal["function", "constructor", "method"] = "function"
    resolution_cid: str = ""

    def __post_init__(self) -> None:
        expected = cid_of_json(self.preimage)
        if self.resolution_cid and self.resolution_cid != expected:
            raise ValueError("source-call resolution CID does not match its preimage")
        object.__setattr__(self, "resolution_cid", expected)

    @property
    def preimage(self):
        return {
            "kind": "source-call-preconstruction-ref",
            "schemaVersion": "1",
            "useSite": self.use_site.wire(),
            "resolvedObjectCid": self.resolved_object_cid,
            "distributionArtifactCid": self.distribution_artifact_cid,
            "sourceCallFrameCid": self.source_call_frame_cid,
            "dispatchKind": self.dispatch_kind,
        }


@dataclass(frozen=True)
class SourceCallPreconstructionGapV1:
    kind: Literal[
        "no-distribution",
        "ambiguous-distribution",
        "artifact-resolution",
        "artifact-mismatch",
        "definition-missing",
        "source-body-gap",
        # The four conditions `opaque-call-target` used to fuse; these ride
        # straight off `ManagerConstructionGapV1.kind`, which owns their
        # definitions.
        "call-graph-cycle",
        "value-call-target",
        "call-target-source-absent",
        "call-target-export-unresolved",
        "non-manager-result",
        "call-binding",
        "dynamic-call-target",
    ]
    use_site: SourceFragmentCoordinateV1
    detail: str


SourceCallPreconstructionV1 = (
    SourceCallPreconstructionRefV1 | SourceCallPreconstructionGapV1
)


__all__ = [
    "SourceCallPreconstructionGapV1",
    "SourceCallPreconstructionRefV1",
    "SourceCallPreconstructionV1",
]
