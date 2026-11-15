"""Closed construction-occurrence identity of an object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypeAlias

from sugar_lift_python_source.canonical import cid_of_json

from .binding_provenance import BindingProvenanceGap
from .fragment import SourceFragment


def _cid(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise BindingProvenanceGap(f"{field} must be an authenticated CID")
    return value


def _generation(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BindingProvenanceGap("constructionGeneration must be non-negative")
    return value


def _exact(raw: object, fields: set[str], owner: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != fields:
        raise BindingProvenanceGap(f"malformed {owner}")
    return raw


def _memento(raw: object, field: str) -> dict[str, Any]:
    raw = _exact(raw, {"file", "span", "source_cid", "cid"}, field)
    span = _exact(raw["span"], {"start", "end"}, f"{field}.span")
    if not isinstance(raw["file"], str) or not raw["file"]:
        raise BindingProvenanceGap(f"malformed {field}.file")
    if not all(
        isinstance(span[key], int) and not isinstance(span[key], bool) for key in span
    ):
        raise BindingProvenanceGap(f"malformed {field}.span")
    if span["start"] < 0 or span["end"] < span["start"]:
        raise BindingProvenanceGap(f"malformed {field}.span")
    _cid(raw["source_cid"], f"{field}.source_cid")
    _cid(raw["cid"], f"{field}.cid")
    return raw


def _checked(preimage: dict[str, Any], observed: object, field: str) -> str:
    cid = _cid(observed, field)
    if cid_of_json(preimage) != cid:
        raise BindingProvenanceGap(f"{field} mismatch")
    return cid


@dataclass(frozen=True)
class SourceObjectCoordinateV1:
    allocation_definition: dict[str, Any]
    call_occurrence: dict[str, Any]
    construction_generation: int
    source_cid: str
    artifact_cid: str
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "source-object-coordinate",
            "schemaVersion": "1",
            "allocationDefinition": self.allocation_definition,
            "callOccurrence": self.call_occurrence,
            "constructionGeneration": self.construction_generation,
            "sourceCid": self.source_cid,
            "artifactCid": self.artifact_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "objectCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls,
        *,
        allocation_definition: SourceFragment,
        call_occurrence: SourceFragment,
        construction_generation: int,
        source_cid: str,
        artifact_cid: str,
    ) -> "SourceObjectCoordinateV1":
        preimage = {
            "kind": "source-object-coordinate",
            "schemaVersion": "1",
            "allocationDefinition": allocation_definition.seal().to_dict(),
            "callOccurrence": call_occurrence.seal().to_dict(),
            "constructionGeneration": _generation(construction_generation),
            "sourceCid": _cid(source_cid, "sourceCid"),
            "artifactCid": _cid(artifact_cid, "artifactCid"),
        }
        return cls(
            preimage["allocationDefinition"],
            preimage["callOccurrence"],
            construction_generation,
            source_cid,
            artifact_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "SourceObjectCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "allocationDefinition",
                "callOccurrence",
                "constructionGeneration",
                "sourceCid",
                "artifactCid",
                "objectCoordinateCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "source-object-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SourceObjectCoordinateV1")
        allocation = _memento(raw["allocationDefinition"], "allocationDefinition")
        occurrence = _memento(raw["callOccurrence"], "callOccurrence")
        generation = _generation(raw["constructionGeneration"])
        source = _cid(raw["sourceCid"], "sourceCid")
        artifact = _cid(raw["artifactCid"], "artifactCid")
        preimage = {
            key: value for key, value in raw.items() if key != "objectCoordinateCid"
        }
        cid = _checked(preimage, raw["objectCoordinateCid"], "object coordinate CID")
        return cls(allocation, occurrence, generation, source, artifact, cid)


@dataclass(frozen=True)
class OpaqueObjectCoordinateV1:
    call_occurrence: dict[str, Any]
    construction_generation: int
    source_cid: str
    artifact_cid: str
    cid: str

    # The static intern table this category owns: CID -> canonical instance.
    _interned: ClassVar[dict[str, "OpaqueObjectCoordinateV1"]] = {}

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "opaque-object-coordinate",
            "schemaVersion": "1",
            "callOccurrence": self.call_occurrence,
            "constructionGeneration": self.construction_generation,
            "sourceCid": self.source_cid,
            "artifactCid": self.artifact_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "objectCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls,
        *,
        call_occurrence: SourceFragment,
        construction_generation: int,
        source_cid: str,
        artifact_cid: str,
    ) -> "OpaqueObjectCoordinateV1":
        preimage = {
            "kind": "opaque-object-coordinate",
            "schemaVersion": "1",
            "callOccurrence": call_occurrence.seal().to_dict(),
            "constructionGeneration": _generation(construction_generation),
            "sourceCid": _cid(source_cid, "sourceCid"),
            "artifactCid": _cid(artifact_cid, "artifactCid"),
        }
        return cls(
            preimage["callOccurrence"],
            construction_generation,
            source_cid,
            artifact_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "OpaqueObjectCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "callOccurrence",
                "constructionGeneration",
                "sourceCid",
                "artifactCid",
                "objectCoordinateCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "opaque-object-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported OpaqueObjectCoordinateV1")
        occurrence = _memento(raw["callOccurrence"], "callOccurrence")
        generation = _generation(raw["constructionGeneration"])
        source = _cid(raw["sourceCid"], "sourceCid")
        artifact = _cid(raw["artifactCid"], "artifactCid")
        # This type OWNS the opaque-object-coordinate category: one static
        # intern table, keyed by the coordinate's own CID. A node carrying an
        # opaque object is a VIEW on the canonical instance; decoding the same
        # coordinate wire (in every snapshot it survives -- asof: 310 decodes,
        # 10 distinct, 31x) does the verifying work once, then returns the
        # interned object. Skips the dominant cost (cid_of_json) on a hit; the
        # cheap structural decode above still runs and the content-address law
        # (same CID => same content) makes the interned instance sound.
        observed = raw["objectCoordinateCid"]
        cached = cls._interned.get(observed)
        if cached is not None:
            return cached
        preimage = {
            key: value for key, value in raw.items() if key != "objectCoordinateCid"
        }
        cid = _checked(preimage, observed, "object coordinate CID")
        result = cls(occurrence, generation, source, artifact, cid)
        cls._interned[cid] = result
        return result


ObjectCoordinateV1: TypeAlias = SourceObjectCoordinateV1 | OpaqueObjectCoordinateV1


def decode_object_coordinate_v1(raw: object) -> ObjectCoordinateV1:
    if not isinstance(raw, dict):
        raise BindingProvenanceGap("malformed ObjectCoordinateV1")
    if raw.get("kind") == "source-object-coordinate":
        return SourceObjectCoordinateV1.decode(raw)
    if raw.get("kind") == "opaque-object-coordinate":
        return OpaqueObjectCoordinateV1.decode(raw)
    raise BindingProvenanceGap("unsupported ObjectCoordinateV1")
