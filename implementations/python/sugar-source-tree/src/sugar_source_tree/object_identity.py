"""Closed construction-occurrence identity and immutable attribute versions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

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
        preimage = {
            key: value for key, value in raw.items() if key != "objectCoordinateCid"
        }
        cid = _checked(preimage, raw["objectCoordinateCid"], "object coordinate CID")
        return cls(occurrence, generation, source, artifact, cid)


ObjectCoordinateV1: TypeAlias = SourceObjectCoordinateV1 | OpaqueObjectCoordinateV1


def decode_object_coordinate_v1(raw: object) -> ObjectCoordinateV1:
    if not isinstance(raw, dict):
        raise BindingProvenanceGap("malformed ObjectCoordinateV1")
    if raw.get("kind") == "source-object-coordinate":
        return SourceObjectCoordinateV1.decode(raw)
    if raw.get("kind") == "opaque-object-coordinate":
        return OpaqueObjectCoordinateV1.decode(raw)
    raise BindingProvenanceGap("unsupported ObjectCoordinateV1")


@dataclass(frozen=True)
class AttributeFieldCoordinateV1:
    object_coordinate: ObjectCoordinateV1
    attribute_name: str
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "attribute-field-coordinate",
            "schemaVersion": "1",
            "objectCoordinate": self.object_coordinate.wire(),
            "attributeName": self.attribute_name,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "fieldCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls, owner: ObjectCoordinateV1, attribute_name: str
    ) -> "AttributeFieldCoordinateV1":
        decode_object_coordinate_v1(owner.wire())
        if not isinstance(attribute_name, str) or not attribute_name.isidentifier():
            raise BindingProvenanceGap("attributeName must be one Python identifier")
        preimage = {
            "kind": "attribute-field-coordinate",
            "schemaVersion": "1",
            "objectCoordinate": owner.wire(),
            "attributeName": attribute_name,
        }
        return cls(owner, attribute_name, cid_of_json(preimage))

    @classmethod
    def decode(cls, raw: object) -> "AttributeFieldCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "objectCoordinate",
                "attributeName",
                "fieldCoordinateCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "attribute-field-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported AttributeFieldCoordinateV1")
        owner = decode_object_coordinate_v1(raw["objectCoordinate"])
        attribute_name = raw["attributeName"]
        if not isinstance(attribute_name, str) or not attribute_name.isidentifier():
            raise BindingProvenanceGap("malformed attributeName")
        preimage = {
            key: value for key, value in raw.items() if key != "fieldCoordinateCid"
        }
        cid = _checked(preimage, raw["fieldCoordinateCid"], "field coordinate CID")
        return cls(owner, attribute_name, cid)


@dataclass(frozen=True)
class SubscriptKeyCoordinateV1:
    constructed_value_cid: str
    construction_testimony_cid: str
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "subscript-key-coordinate",
            "schemaVersion": "1",
            "constructedValueCid": self.constructed_value_cid,
            "constructionTestimonyCid": self.construction_testimony_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "keyCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls, *, constructed_value_cid: str, construction_testimony_cid: str
    ) -> "SubscriptKeyCoordinateV1":
        preimage = {
            "kind": "subscript-key-coordinate",
            "schemaVersion": "1",
            "constructedValueCid": _cid(constructed_value_cid, "constructedValueCid"),
            "constructionTestimonyCid": _cid(
                construction_testimony_cid, "constructionTestimonyCid"
            ),
        }
        return cls(
            constructed_value_cid,
            construction_testimony_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "SubscriptKeyCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "constructedValueCid",
                "constructionTestimonyCid",
                "keyCoordinateCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "subscript-key-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SubscriptKeyCoordinateV1")
        value = _cid(raw["constructedValueCid"], "constructedValueCid")
        testimony = _cid(raw["constructionTestimonyCid"], "constructionTestimonyCid")
        preimage = {
            key: value for key, value in raw.items() if key != "keyCoordinateCid"
        }
        cid = _checked(preimage, raw["keyCoordinateCid"], "key coordinate CID")
        return cls(value, testimony, cid)


@dataclass(frozen=True)
class SubscriptFieldCoordinateV1:
    object_coordinate: ObjectCoordinateV1
    key_coordinate: SubscriptKeyCoordinateV1
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "subscript-field-coordinate",
            "schemaVersion": "1",
            "objectCoordinate": self.object_coordinate.wire(),
            "keyCoordinate": self.key_coordinate.wire(),
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "fieldCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls, owner: ObjectCoordinateV1, key: SubscriptKeyCoordinateV1
    ) -> "SubscriptFieldCoordinateV1":
        decode_object_coordinate_v1(owner.wire())
        SubscriptKeyCoordinateV1.decode(key.wire())
        preimage = {
            "kind": "subscript-field-coordinate",
            "schemaVersion": "1",
            "objectCoordinate": owner.wire(),
            "keyCoordinate": key.wire(),
        }
        return cls(owner, key, cid_of_json(preimage))

    @classmethod
    def decode(cls, raw: object) -> "SubscriptFieldCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "objectCoordinate",
                "keyCoordinate",
                "fieldCoordinateCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "subscript-field-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SubscriptFieldCoordinateV1")
        owner = decode_object_coordinate_v1(raw["objectCoordinate"])
        key_coordinate = SubscriptKeyCoordinateV1.decode(raw["keyCoordinate"])
        preimage = {
            key: value for key, value in raw.items() if key != "fieldCoordinateCid"
        }
        cid = _checked(preimage, raw["fieldCoordinateCid"], "field coordinate CID")
        return cls(owner, key_coordinate, cid)


@dataclass(frozen=True)
class AttributeFieldVersionV1:
    owner: ObjectCoordinateV1
    field: AttributeFieldCoordinateV1
    store_occurrence: dict[str, Any]
    construction_generation: int
    stored_value_testimony_cid: str
    prior_version_cid: str | None
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "attribute-field-version",
            "schemaVersion": "1",
            "objectCoordinate": self.owner.wire(),
            "fieldCoordinate": self.field.wire(),
            "storeOccurrence": self.store_occurrence,
            "constructionGeneration": self.construction_generation,
            "storedValueTestimonyCid": self.stored_value_testimony_cid,
            "priorVersionCid": self.prior_version_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "fieldVersionCid": self.cid}

    @classmethod
    def mint(
        cls,
        *,
        owner: ObjectCoordinateV1,
        field: AttributeFieldCoordinateV1,
        store_occurrence: SourceFragment,
        construction_generation: int,
        stored_value_testimony_cid: str,
        prior_version_cid: str | None,
    ) -> "AttributeFieldVersionV1":
        decode_object_coordinate_v1(owner.wire())
        AttributeFieldCoordinateV1.decode(field.wire())
        if field.object_coordinate.cid != owner.cid:
            raise BindingProvenanceGap("field owner coordinate mismatch")
        if prior_version_cid is not None:
            _cid(prior_version_cid, "priorVersionCid")
        preimage = {
            "kind": "attribute-field-version",
            "schemaVersion": "1",
            "objectCoordinate": owner.wire(),
            "fieldCoordinate": field.wire(),
            "storeOccurrence": store_occurrence.seal().to_dict(),
            "constructionGeneration": _generation(construction_generation),
            "storedValueTestimonyCid": _cid(
                stored_value_testimony_cid, "storedValueTestimonyCid"
            ),
            "priorVersionCid": prior_version_cid,
        }
        return cls(
            owner,
            field,
            preimage["storeOccurrence"],
            construction_generation,
            stored_value_testimony_cid,
            prior_version_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "AttributeFieldVersionV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "objectCoordinate",
                "fieldCoordinate",
                "storeOccurrence",
                "constructionGeneration",
                "storedValueTestimonyCid",
                "priorVersionCid",
                "fieldVersionCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "attribute-field-version" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported AttributeFieldVersionV1")
        owner = decode_object_coordinate_v1(raw["objectCoordinate"])
        field = AttributeFieldCoordinateV1.decode(raw["fieldCoordinate"])
        if field.object_coordinate.cid != owner.cid:
            raise BindingProvenanceGap("field owner coordinate mismatch")
        store = _memento(raw["storeOccurrence"], "storeOccurrence")
        generation = _generation(raw["constructionGeneration"])
        stored = _cid(raw["storedValueTestimonyCid"], "storedValueTestimonyCid")
        prior = raw["priorVersionCid"]
        if prior is not None:
            prior = _cid(prior, "priorVersionCid")
        preimage = {
            key: value for key, value in raw.items() if key != "fieldVersionCid"
        }
        cid = _checked(preimage, raw["fieldVersionCid"], "field version CID")
        return cls(owner, field, store, generation, stored, prior, cid)


@dataclass(frozen=True)
class SubscriptFieldVersionV1:
    owner: ObjectCoordinateV1
    field: SubscriptFieldCoordinateV1
    store_occurrence: dict[str, Any]
    construction_generation: int
    stored_value_testimony_cid: str
    prior_version_cid: str | None
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "subscript-field-version",
            "schemaVersion": "1",
            "objectCoordinate": self.owner.wire(),
            "fieldCoordinate": self.field.wire(),
            "storeOccurrence": self.store_occurrence,
            "constructionGeneration": self.construction_generation,
            "storedValueTestimonyCid": self.stored_value_testimony_cid,
            "priorVersionCid": self.prior_version_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "fieldVersionCid": self.cid}

    @classmethod
    def mint(
        cls,
        *,
        owner: ObjectCoordinateV1,
        field: SubscriptFieldCoordinateV1,
        store_occurrence: SourceFragment,
        construction_generation: int,
        stored_value_testimony_cid: str,
        prior_version_cid: str | None,
    ) -> "SubscriptFieldVersionV1":
        decode_object_coordinate_v1(owner.wire())
        SubscriptFieldCoordinateV1.decode(field.wire())
        if field.object_coordinate.cid != owner.cid:
            raise BindingProvenanceGap("field owner coordinate mismatch")
        if prior_version_cid is not None:
            _cid(prior_version_cid, "priorVersionCid")
        preimage = {
            "kind": "subscript-field-version",
            "schemaVersion": "1",
            "objectCoordinate": owner.wire(),
            "fieldCoordinate": field.wire(),
            "storeOccurrence": store_occurrence.seal().to_dict(),
            "constructionGeneration": _generation(construction_generation),
            "storedValueTestimonyCid": _cid(
                stored_value_testimony_cid, "storedValueTestimonyCid"
            ),
            "priorVersionCid": prior_version_cid,
        }
        return cls(
            owner,
            field,
            preimage["storeOccurrence"],
            construction_generation,
            stored_value_testimony_cid,
            prior_version_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "SubscriptFieldVersionV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "objectCoordinate",
                "fieldCoordinate",
                "storeOccurrence",
                "constructionGeneration",
                "storedValueTestimonyCid",
                "priorVersionCid",
                "fieldVersionCid",
            },
            cls.__name__,
        )
        if raw["kind"] != "subscript-field-version" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SubscriptFieldVersionV1")
        owner = decode_object_coordinate_v1(raw["objectCoordinate"])
        field = SubscriptFieldCoordinateV1.decode(raw["fieldCoordinate"])
        if field.object_coordinate.cid != owner.cid:
            raise BindingProvenanceGap("field owner coordinate mismatch")
        store = _memento(raw["storeOccurrence"], "storeOccurrence")
        generation = _generation(raw["constructionGeneration"])
        stored = _cid(raw["storedValueTestimonyCid"], "storedValueTestimonyCid")
        prior = raw["priorVersionCid"]
        if prior is not None:
            prior = _cid(prior, "priorVersionCid")
        preimage = {
            key: value for key, value in raw.items() if key != "fieldVersionCid"
        }
        cid = _checked(preimage, raw["fieldVersionCid"], "field version CID")
        return cls(owner, field, store, generation, stored, prior, cid)
