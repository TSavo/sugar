"""Closed, content-addressed identity for temporal Python bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from sugar_lift_python_source.canonical import cid_of_json

from .fragment import SourceFragment


class BindingProvenanceGap(ValueError):
    """A binding coordinate/state cannot enter the authenticated wire."""


def _cid(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise BindingProvenanceGap(f"{field} must be an authenticated CID")
    return value


def _exact(raw: object, fields: set[str], owner: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != fields:
        raise BindingProvenanceGap(f"malformed {owner}")
    return raw


@dataclass(frozen=True)
class BindingCoordinateV1:
    scope_owner_cid: str
    binding_site: dict[str, Any]
    projection_path: tuple[str | int, ...]
    cid: str

    # This type owns the binding-coordinate category: CID -> canonical instance.
    _interned: ClassVar[dict[str, "BindingCoordinateV1"]] = {}

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "binding-coordinate",
            "schemaVersion": "1",
            "scopeOwnerCid": self.scope_owner_cid,
            "bindingSite": self.binding_site,
            "projectionPath": list(self.projection_path),
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "bindingCoordinateCid": self.cid}

    @classmethod
    def mint(
        cls,
        scope_owner_cid: str,
        binding_site: SourceFragment,
        projection_path: tuple[str | int, ...],
    ) -> "BindingCoordinateV1":
        _cid(scope_owner_cid, "scopeOwnerCid")
        if not projection_path or not all(
            isinstance(part, (str, int)) and not isinstance(part, bool)
            for part in projection_path
        ):
            raise BindingProvenanceGap(
                "projectionPath must be one non-empty structural path"
            )
        site = binding_site.seal().to_dict()
        preimage = {
            "kind": "binding-coordinate",
            "schemaVersion": "1",
            "scopeOwnerCid": scope_owner_cid,
            "bindingSite": site,
            "projectionPath": list(projection_path),
        }
        return cls(scope_owner_cid, site, projection_path, cid_of_json(preimage))

    @classmethod
    def decode(cls, raw: object) -> "BindingCoordinateV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "scopeOwnerCid",
                "bindingSite",
                "projectionPath",
                "bindingCoordinateCid",
            },
            "BindingCoordinateV1",
        )
        if raw["kind"] != "binding-coordinate" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported BindingCoordinateV1")
        _cid(raw["scopeOwnerCid"], "scopeOwnerCid")
        site = _decode_source_memento(raw["bindingSite"])
        path = raw["projectionPath"]
        if (
            not isinstance(path, list)
            or not path
            or not all(
                isinstance(part, (str, int)) and not isinstance(part, bool)
                for part in path
            )
        ):
            raise BindingProvenanceGap("malformed projectionPath")
        observed = _cid(raw["bindingCoordinateCid"], "bindingCoordinateCid")
        cached = cls._interned.get(observed)
        if cached is not None:
            return cached
        preimage = {
            key: value for key, value in raw.items() if key != "bindingCoordinateCid"
        }
        if cid_of_json(preimage) != observed:
            raise BindingProvenanceGap("coordinate CID mismatch")
        result = cls(raw["scopeOwnerCid"], site, tuple(path), observed)
        cls._interned[observed] = result
        return result


@dataclass(frozen=True)
class ConstructedValueTestimonyV1:
    source_fragment_cid: str
    semantic_value_cid: str
    cid: str

    # This type owns the constructed-value-testimony category.
    _interned: ClassVar[dict[str, "ConstructedValueTestimonyV1"]] = {}

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "constructed-value-testimony",
            "schemaVersion": "1",
            "sourceFragmentCid": self.source_fragment_cid,
            "semanticValueCid": self.semantic_value_cid,
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "constructedValueTestimonyCid": self.cid}

    @classmethod
    def mint(
        cls, source_fragment: SourceFragment, semantic_value_cid: str
    ) -> "ConstructedValueTestimonyV1":
        _cid(semantic_value_cid, "semanticValueCid")
        preimage = {
            "kind": "constructed-value-testimony",
            "schemaVersion": "1",
            "sourceFragmentCid": source_fragment.seal().cid,
            "semanticValueCid": semantic_value_cid,
        }
        return cls(
            preimage["sourceFragmentCid"],
            semantic_value_cid,
            cid_of_json(preimage),
        )

    @classmethod
    def decode(cls, raw: object) -> "ConstructedValueTestimonyV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "sourceFragmentCid",
                "semanticValueCid",
                "constructedValueTestimonyCid",
            },
            "ConstructedValueTestimonyV1",
        )
        if raw["kind"] != "constructed-value-testimony" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported ConstructedValueTestimonyV1")
        _cid(raw["sourceFragmentCid"], "sourceFragmentCid")
        _cid(raw["semanticValueCid"], "semanticValueCid")
        observed = _cid(
            raw["constructedValueTestimonyCid"], "constructedValueTestimonyCid"
        )
        cached = cls._interned.get(observed)
        if cached is not None:
            return cached
        preimage = {
            key: value
            for key, value in raw.items()
            if key != "constructedValueTestimonyCid"
        }
        if cid_of_json(preimage) != observed:
            raise BindingProvenanceGap("constructed testimony CID mismatch")
        result = cls(raw["sourceFragmentCid"], raw["semanticValueCid"], observed)
        cls._interned[observed] = result
        return result


@dataclass(frozen=True)
class BoundBindingStateV1:
    testimony: ConstructedValueTestimonyV1 | None


@dataclass(frozen=True)
class UnboundBindingStateV1:
    cause_fragment_cid: str


@dataclass(frozen=True)
class GuardedBindingStateV1:
    guard_formula_cid: str
    when_true_state_cid: str
    when_false_state_cid: str


@dataclass(frozen=True)
class LoopProjectedFaceV1:
    """One sealed completed face of a loop post-state."""

    completion_kind: str
    guard_formula_cid: str
    state_cid: str
    exit_partition_arity: int | None = None


@dataclass(frozen=True)
class LoopProjectedBindingStateV1:
    """A loop post-state sealed as an n-way partition, never folded to binary.

    A multi-face loop post-binding is a genuine n-way join: the faces are the
    loop's own completion routes, and no two of them hold at once. Folding them
    into nested ``GuardedBindingStateV1`` would require picking an order and
    naming one face the else-branch, which asserts a fallthrough the producer
    never declared. The faces are therefore sealed AS a partition, keyed by the
    producer occurrence that minted them.

    ``target_cid`` is that occurrence. Two loops in one function are two
    occurrences and share no exclusion, so a downstream consumer keying on
    anything weaker (a name, a completion kind, a value type) is the exact trap
    the same-type partition law refuses -- the identical reason
    ``LoopGuardedProjection`` carries the same field.
    """

    target_cid: str
    faces: tuple[LoopProjectedFaceV1, ...]

    def __post_init__(self) -> None:
        if not self.faces:
            raise BindingProvenanceGap("loop projected state requires faces")
        kinds = [face.completion_kind for face in self.faces]
        if len(set(kinds)) != len(kinds):
            raise BindingProvenanceGap(
                "loop projected state faces must be one per completion kind"
            )
        if kinds != sorted(kinds):
            raise BindingProvenanceGap(
                "loop projected state faces must be completion-kind sorted"
            )


BindingStateV1 = (
    BoundBindingStateV1
    | UnboundBindingStateV1
    | GuardedBindingStateV1
    | LoopProjectedBindingStateV1
)


@dataclass(frozen=True)
class BindingEntryV1:
    coordinate: BindingCoordinateV1
    state: BindingStateV1

    def constructed_value_testimony_cid(self) -> str:
        if not isinstance(self.state, BoundBindingStateV1):
            raise BindingProvenanceGap("binding entry is not a bound value")
        if self.state.testimony is None:
            raise BindingProvenanceGap("constructed-value testimony unavailable")
        ConstructedValueTestimonyV1.decode(self.state.testimony.wire())
        return self.state.testimony.cid

    def wire(self) -> dict[str, Any]:
        return {"coordinate": self.coordinate.wire(), "state": _state_wire(self.state)}

    @classmethod
    def decode(cls, raw: object) -> "BindingEntryV1":
        raw = _exact(raw, {"coordinate", "state"}, "BindingEntryV1")
        return cls(
            BindingCoordinateV1.decode(raw["coordinate"]), _decode_state(raw["state"])
        )


@dataclass(frozen=True)
class SubstitutionTraceRecordV1:
    statement_source: dict[str, Any]
    pre_entries: tuple[BindingEntryV1, ...]
    post_entries: tuple[BindingEntryV1, ...]
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "substitution-trace-record",
            "schemaVersion": "1",
            "statementSource": self.statement_source,
            "preEntries": [entry.wire() for entry in self.pre_entries],
            "postEntries": [entry.wire() for entry in self.post_entries],
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "recordCid": self.cid}

    @classmethod
    def mint(
        cls,
        statement_source: SourceFragment,
        pre_entries: tuple[BindingEntryV1, ...],
        post_entries: tuple[BindingEntryV1, ...],
    ) -> "SubstitutionTraceRecordV1":
        pre = tuple(sorted(pre_entries, key=lambda entry: entry.coordinate.cid))
        post = tuple(sorted(post_entries, key=lambda entry: entry.coordinate.cid))
        source = statement_source.seal().to_dict()
        value = cls(source, pre, post, "")
        return cls(source, pre, post, cid_of_json(value.preimage))

    @classmethod
    def decode(cls, raw: object) -> "SubstitutionTraceRecordV1":
        raw = _exact(
            raw,
            {
                "kind",
                "schemaVersion",
                "statementSource",
                "preEntries",
                "postEntries",
                "recordCid",
            },
            "SubstitutionTraceRecordV1",
        )
        if raw["kind"] != "substitution-trace-record" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SubstitutionTraceRecordV1")
        source = _decode_source_memento(raw["statementSource"])
        pre = _decode_entries(raw["preEntries"])
        post = _decode_entries(raw["postEntries"])
        observed = _cid(raw["recordCid"], "recordCid")
        preimage = {key: value for key, value in raw.items() if key != "recordCid"}
        if cid_of_json(preimage) != observed:
            raise BindingProvenanceGap("trace record CID mismatch")
        return cls(source, pre, post, observed)


@dataclass(frozen=True)
class SubstitutionTraceV1:
    scope_owner_cid: str
    records: tuple[SubstitutionTraceRecordV1, ...]
    cid: str

    @property
    def preimage(self) -> dict[str, Any]:
        return {
            "kind": "substitution-trace",
            "schemaVersion": "1",
            "scopeOwnerCid": self.scope_owner_cid,
            "records": [record.wire() for record in self.records],
        }

    def wire(self) -> dict[str, Any]:
        return {**self.preimage, "traceCid": self.cid}

    @classmethod
    def mint(
        cls, scope_owner_cid: str, records: tuple[SubstitutionTraceRecordV1, ...]
    ) -> "SubstitutionTraceV1":
        _cid(scope_owner_cid, "scopeOwnerCid")
        value = cls(scope_owner_cid, records, "")
        return cls(scope_owner_cid, records, cid_of_json(value.preimage))

    @classmethod
    def decode(cls, raw: object) -> "SubstitutionTraceV1":
        raw = _exact(
            raw,
            {"kind", "schemaVersion", "scopeOwnerCid", "records", "traceCid"},
            "SubstitutionTraceV1",
        )
        if raw["kind"] != "substitution-trace" or raw["schemaVersion"] != "1":
            raise BindingProvenanceGap("unsupported SubstitutionTraceV1")
        _cid(raw["scopeOwnerCid"], "scopeOwnerCid")
        if not isinstance(raw["records"], list):
            raise BindingProvenanceGap("trace records must be an array")
        records = tuple(
            SubstitutionTraceRecordV1.decode(item) for item in raw["records"]
        )
        observed = _cid(raw["traceCid"], "traceCid")
        preimage = {key: value for key, value in raw.items() if key != "traceCid"}
        if cid_of_json(preimage) != observed:
            raise BindingProvenanceGap("trace CID mismatch")
        return cls(raw["scopeOwnerCid"], records, observed)


def _decode_source_memento(raw: object) -> dict[str, Any]:
    raw = _exact(raw, {"file", "span", "source_cid", "cid"}, "SourceMemento")
    span = _exact(raw["span"], {"start", "end"}, "SourceMemento span")
    if not all(
        isinstance(span[key], int) and not isinstance(span[key], bool) for key in span
    ):
        raise BindingProvenanceGap("source span offsets must be integers")
    _cid(raw["source_cid"], "source_cid")
    _cid(raw["cid"], "cid")
    if not isinstance(raw["file"], str):
        raise BindingProvenanceGap("source file must be a string")
    return raw


def _state_wire(state: BindingStateV1) -> dict[str, Any]:
    if isinstance(state, BoundBindingStateV1):
        if state.testimony is None:
            raise BindingProvenanceGap("constructed-value testimony unavailable")
        return {"kind": "bound", "testimony": state.testimony.wire()}
    if isinstance(state, UnboundBindingStateV1):
        return {
            "kind": "unbound",
            "causeFragmentCid": _cid(state.cause_fragment_cid, "causeFragmentCid"),
        }
    if isinstance(state, GuardedBindingStateV1):
        return {
            "kind": "guarded",
            "guardFormulaCid": _cid(state.guard_formula_cid, "guardFormulaCid"),
            "whenTrueStateCid": _cid(state.when_true_state_cid, "whenTrueStateCid"),
            "whenFalseStateCid": _cid(state.when_false_state_cid, "whenFalseStateCid"),
        }
    if isinstance(state, LoopProjectedBindingStateV1):
        return {
            "kind": "loopProjected",
            "targetCid": _cid(state.target_cid, "targetCid"),
            "faces": [
                {
                    "completionKind": face.completion_kind,
                    "guardFormulaCid": _cid(face.guard_formula_cid, "guardFormulaCid"),
                    "stateCid": _cid(face.state_cid, "stateCid"),
                    "exitPartitionArity": face.exit_partition_arity,
                }
                for face in state.faces
            ],
        }
    raise BindingProvenanceGap(f"unknown binding state {type(state).__name__}")


def _decode_state(raw: object) -> BindingStateV1:
    if not isinstance(raw, dict):
        raise BindingProvenanceGap("malformed BindingStateV1")
    kind = raw.get("kind")
    if kind == "bound":
        raw = _exact(raw, {"kind", "testimony"}, "bound BindingStateV1")
        return BoundBindingStateV1(ConstructedValueTestimonyV1.decode(raw["testimony"]))
    if kind == "unbound":
        raw = _exact(raw, {"kind", "causeFragmentCid"}, "unbound BindingStateV1")
        return UnboundBindingStateV1(_cid(raw["causeFragmentCid"], "causeFragmentCid"))
    if kind == "guarded":
        raw = _exact(
            raw,
            {"kind", "guardFormulaCid", "whenTrueStateCid", "whenFalseStateCid"},
            "guarded BindingStateV1",
        )
        return GuardedBindingStateV1(
            _cid(raw["guardFormulaCid"], "guardFormulaCid"),
            _cid(raw["whenTrueStateCid"], "whenTrueStateCid"),
            _cid(raw["whenFalseStateCid"], "whenFalseStateCid"),
        )
    if kind == "loopProjected":
        raw = _exact(
            raw, {"kind", "targetCid", "faces"}, "loopProjected BindingStateV1"
        )
        if not isinstance(raw["faces"], list):
            raise BindingProvenanceGap("loop projected faces must be an array")
        faces = []
        for item in raw["faces"]:
            item = _exact(
                item,
                {"completionKind", "guardFormulaCid", "stateCid", "exitPartitionArity"},
                "loopProjected face",
            )
            arity = item["exitPartitionArity"]
            if arity is not None and not isinstance(arity, int):
                raise BindingProvenanceGap("exitPartitionArity must be an int or null")
            faces.append(
                LoopProjectedFaceV1(
                    item["completionKind"],
                    _cid(item["guardFormulaCid"], "guardFormulaCid"),
                    _cid(item["stateCid"], "stateCid"),
                    arity,
                )
            )
        return LoopProjectedBindingStateV1(
            _cid(raw["targetCid"], "targetCid"), tuple(faces)
        )
    raise BindingProvenanceGap("unknown BindingStateV1 variant")


def _decode_entries(raw: object) -> tuple[BindingEntryV1, ...]:
    if not isinstance(raw, list):
        raise BindingProvenanceGap("binding entries must be an array")
    entries = tuple(BindingEntryV1.decode(item) for item in raw)
    cids = [entry.coordinate.cid for entry in entries]
    if cids != sorted(cids) or len(cids) != len(set(cids)):
        raise BindingProvenanceGap("binding entries must be unique and CID-sorted")
    return entries


__all__ = [
    "BindingCoordinateV1",
    "BindingEntryV1",
    "BindingProvenanceGap",
    "BoundBindingStateV1",
    "ConstructedValueTestimonyV1",
    "GuardedBindingStateV1",
    "LoopProjectedBindingStateV1",
    "LoopProjectedFaceV1",
    "SubstitutionTraceRecordV1",
    "SubstitutionTraceV1",
    "UnboundBindingStateV1",
]
