from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context_manager_contract import _json_value
from sugar_lift_py_tests.ir import PrimitiveSort

ParameterKindV1 = Literal[
    "positional-only",
    "positional-or-keyword",
    "variadic-positional",
    "keyword-only",
    "variadic-keyword",
]


def _cid(value: Any) -> str:
    # One encode of the Value tree; no JSON decode/re-encode of the same bytes.
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


@dataclass(frozen=True)
class FormalParameterCoordinateV1:
    owner_source_identity_cid: str
    owner_definition_locus: SourceFragmentCoordinateV1
    declaration_locus: SourceFragmentCoordinateV1
    ordinal: int
    parameter_kind: ParameterKindV1
    declared_name: str
    sort: PrimitiveSort
    coordinate_cid: str
    kind: str = "formal-parameter-coordinate"
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not self.owner_source_identity_cid.startswith("blake3-512:"):
            raise ValueError("formal owner requires a source identity CID")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ValueError("formal ordinal must be nonnegative")
        if not self.declared_name:
            raise ValueError("formal declared name must be nonempty")
        if self.parameter_kind not in {
            "positional-only",
            "positional-or-keyword",
            "variadic-positional",
            "keyword-only",
            "variadic-keyword",
        }:
            raise ValueError("formal parameter kind is unknown")
        if self.sort != PrimitiveSort("Value"):
            raise ValueError("formal sort is not the authenticated Python Value sort")
        if self.coordinate_cid != _cid(self.preimage()):
            raise ValueError("formal coordinate CID is stale")

    @classmethod
    def mint(
        cls,
        *,
        owner_source_identity_cid: str,
        owner_definition_locus: SourceFragmentCoordinateV1,
        declaration_locus: SourceFragmentCoordinateV1,
        ordinal: int,
        parameter_kind: ParameterKindV1,
        declared_name: str,
        sort: PrimitiveSort,
    ) -> "FormalParameterCoordinateV1":
        preimage = {
            "kind": "formal-parameter-coordinate",
            "schemaVersion": "1",
            "ownerSourceIdentityCid": owner_source_identity_cid,
            "ownerDefinitionLocus": owner_definition_locus.wire(),
            "declarationLocus": declaration_locus.wire(),
            "ordinal": ordinal,
            "parameterKind": parameter_kind,
            "declaredName": declared_name,
            "sort": {"kind": "primitive", "name": sort.name},
        }
        return cls(
            owner_source_identity_cid,
            owner_definition_locus,
            declaration_locus,
            ordinal,
            parameter_kind,
            declared_name,
            sort,
            _cid(preimage),
        )

    def preimage(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "ownerDefinitionLocus": self.owner_definition_locus.wire(),
            "declarationLocus": self.declaration_locus.wire(),
            "ordinal": self.ordinal,
            "parameterKind": self.parameter_kind,
            "declaredName": self.declared_name,
            "sort": {"kind": "primitive", "name": self.sort.name},
        }

    def to_value(self) -> dict[str, Any]:
        return {**self.preimage(), "coordinateCid": self.coordinate_cid}
