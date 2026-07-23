from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sugar_lift_python_source.canonical import cid_of_json

from .context_manager_resolution import SourceFragmentCoordinateV1


@dataclass(frozen=True)
class SourceVisibleCallFrameV1:
    """A body constructed by FunctionDef through the ordinary tree door."""

    source_identity_cid: str
    definition_site: SourceFragmentCoordinateV1
    definition_fragment_cid: str
    parameters: tuple[str, ...]
    body: object = field(compare=False)
    frame_cid: str = field(init=False)

    def __post_init__(self) -> None:
        preimage = {
            "kind": "source-visible-call-frame",
            "schemaVersion": "1",
            "sourceIdentityCid": self.source_identity_cid,
            "definitionSite": self.definition_site.wire(),
            "definitionFragmentCid": self.definition_fragment_cid,
            "parameters": list(self.parameters),
        }
        object.__setattr__(self, "frame_cid", cid_of_json(preimage))


@dataclass(frozen=True)
class AwaitingBindingCoordinateCallFrameV1:
    """Typed boundary until the shared BindingCoordinateV1 spine lands."""

    source_identity_cid: str
    definition_site: SourceFragmentCoordinateV1
    parameters: tuple[str, ...]
    kind: Literal["awaiting-binding-coordinate"] = "awaiting-binding-coordinate"


SourceCallFrameV1 = SourceVisibleCallFrameV1 | AwaitingBindingCoordinateCallFrameV1
