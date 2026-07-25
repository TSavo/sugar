"""Closed, content-addressed LoopConstructionV1 wire.

Every CID is BLAKE3-512 over canonical JCS of the record without its own CID.
Decoding is admission: exact keys, closed variants, recomputed CIDs, and resolved
child references are required before a loop graph becomes construction input.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import _json_value
from .context_manager_resolution import SourceFragmentCoordinateV1


class LoopWireError(ValueError):
    pass


def _hash_json(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def _require_cid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise LoopWireError(f"{field} must be a CID")
    return value


def _exact(raw: Any, fields: set[str], owner: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != fields:
        raise LoopWireError(f"malformed {owner}")
    return raw


def seal_loop_record(preimage: dict[str, Any], cid_field: str) -> dict[str, Any]:
    if cid_field in preimage:
        raise LoopWireError(f"{cid_field} must not contain its own CID in preimage")
    return {**deepcopy(preimage), cid_field: _hash_json(preimage)}


def _validate_seal(raw: dict[str, Any], cid_field: str, owner: str) -> str:
    cid = _require_cid(raw.get(cid_field), cid_field)
    preimage = {key: value for key, value in raw.items() if key != cid_field}
    if _hash_json(preimage) != cid:
        raise LoopWireError(f"{cid_field} mismatch in {owner}")
    return cid


@dataclass(frozen=True)
class LoopTargetCoordinateV1:
    loop_kind: str
    source_fragment: SourceFragmentCoordinateV1
    target_cid: str

    def wire(self) -> dict[str, Any]:
        return {
            "kind": "python-loop-target",
            "schemaVersion": "1",
            "loopKind": self.loop_kind,
            "sourceFragment": self.source_fragment.wire(),
            "targetCid": self.target_cid,
        }


def mint_loop_target_coordinate_v1(
    loop_kind: str, source_fragment: SourceFragmentCoordinateV1 | dict[str, Any]
) -> LoopTargetCoordinateV1:
    if loop_kind not in {"For", "AsyncFor", "While"}:
        raise LoopWireError("unknown loopKind")
    coordinate = (
        source_fragment
        if isinstance(source_fragment, SourceFragmentCoordinateV1)
        else SourceFragmentCoordinateV1.decode(source_fragment)
    )
    preimage = {
        "kind": "python-loop-target",
        "schemaVersion": "1",
        "loopKind": loop_kind,
        "sourceFragment": coordinate.wire(),
    }
    return LoopTargetCoordinateV1(loop_kind, coordinate, _hash_json(preimage))


def decode_loop_target_coordinate_v1(raw: Any) -> LoopTargetCoordinateV1:
    raw = _exact(
        raw,
        {"kind", "schemaVersion", "loopKind", "sourceFragment", "targetCid"},
        "LoopTargetCoordinateV1",
    )
    if raw["kind"] != "python-loop-target" or raw["schemaVersion"] != "1":
        raise LoopWireError("unsupported LoopTargetCoordinateV1")
    minted = mint_loop_target_coordinate_v1(raw["loopKind"], raw["sourceFragment"])
    if minted.target_cid != _require_cid(raw["targetCid"], "targetCid"):
        raise LoopWireError("targetCid mismatch")
    return minted


@dataclass(frozen=True)
class BindingStateV1:
    entries: tuple[dict[str, Any], ...]
    state_cid: str
    raw: dict[str, Any]


def _decode_binding_entry(raw: Any) -> tuple[str, dict[str, Any]]:
    raw = _exact(raw, {"coordinate", "state"}, "BindingEntryV1")
    coordinate = _exact(
        raw["coordinate"],
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
    if coordinate["kind"] != "binding-coordinate" or coordinate["schemaVersion"] != "1":
        raise LoopWireError("unsupported BindingCoordinateV1")
    coordinate_cid = _validate_seal(
        coordinate, "bindingCoordinateCid", "BindingCoordinateV1"
    )
    _require_cid(coordinate["scopeOwnerCid"], "scopeOwnerCid")
    state = raw["state"]
    if not isinstance(state, dict):
        raise LoopWireError("malformed BindingStateV1")
    kind = state.get("kind")
    if kind == "bound":
        state = _exact(state, {"kind", "testimony"}, "bound BindingStateV1")
        testimony = _exact(
            state["testimony"],
            {
                "kind",
                "schemaVersion",
                "sourceFragmentCid",
                "semanticValueCid",
                "constructedValueTestimonyCid",
            },
            "ConstructedValueTestimonyV1",
        )
        if (
            testimony["kind"] != "constructed-value-testimony"
            or testimony["schemaVersion"] != "1"
        ):
            raise LoopWireError("unsupported ConstructedValueTestimonyV1")
        _validate_seal(
            testimony,
            "constructedValueTestimonyCid",
            "ConstructedValueTestimonyV1",
        )
    elif kind == "unbound":
        state = _exact(state, {"kind", "causeFragmentCid"}, "unbound BindingStateV1")
        _require_cid(state["causeFragmentCid"], "causeFragmentCid")
    elif kind == "guarded":
        state = _exact(
            state,
            {"kind", "guardFormulaCid", "whenTrueStateCid", "whenFalseStateCid"},
            "guarded BindingStateV1",
        )
        for field in ("guardFormulaCid", "whenTrueStateCid", "whenFalseStateCid"):
            _require_cid(state[field], field)
    else:
        raise LoopWireError("unknown BindingStateV1 variant")
    return coordinate_cid, deepcopy(raw)


def decode_binding_state_v1(raw: Any) -> BindingStateV1:
    raw = _exact(
        raw,
        {"kind", "schemaVersion", "entries", "stateCid"},
        "BindingStateV1",
    )
    if raw["kind"] != "binding-state" or raw["schemaVersion"] != "1":
        raise LoopWireError("unsupported BindingStateV1")
    if not isinstance(raw["entries"], list):
        raise LoopWireError("BindingStateV1 entries must be an array")
    entries = []
    coordinates = []
    for entry in raw["entries"]:
        coordinate, decoded = _decode_binding_entry(entry)
        coordinates.append(coordinate)
        entries.append(decoded)
    if coordinates != sorted(coordinates) or len(coordinates) != len(set(coordinates)):
        raise LoopWireError("BindingStateV1 entries must be strictly CID-sorted")
    state_cid = _validate_seal(raw, "stateCid", "BindingStateV1")
    return BindingStateV1(tuple(entries), state_cid, deepcopy(raw))


def seal_binding_state_v1(entries: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    decoded = [_decode_binding_entry(entry) for entry in entries]
    decoded.sort(key=lambda item: item[0])
    coordinates = [coordinate for coordinate, _entry in decoded]
    if len(coordinates) != len(set(coordinates)):
        raise LoopWireError("BindingStateV1 entries must be unique")
    preimage = {
        "kind": "binding-state",
        "schemaVersion": "1",
        "entries": [entry for _coordinate, entry in decoded],
    }
    return seal_loop_record(preimage, "stateCid")


_RECORD_CID_FIELDS = {
    "loop-completed-face": "completedFaceCid",
    "loop-outward-halted-face": "outwardHaltedFaceCid",
    "loop-binder-transform": "binderTransformCid",
    "loop-body-transform": "bodyTransformCid",
    "loop-test-transform": "testTransformCid",
    "loop-iterator-testimony": "iteratorTestimonyCid",
    "for-operation": "operationCid",
    "while-operation": "operationCid",
    "loop-latch-obligation": "latchObligationCid",
    "loop-continue-latch-obligation": "continueLatchObligationCid",
    "loop-break-exit-obligation": "breakExitObligationCid",
    "loop-exhaustion-exit-obligation": "exhaustionExitObligationCid",
    "loop-else-exhaustion-obligation": "elseExhaustionObligationCid",
    "loop-post-binding": "postBindingObligationCid",
}


_EXACT_FIELDS = {
    "loop-completed-face": {
        "kind",
        "schemaVersion",
        "targetCid",
        "completionKind",
        "guardFormulaCid",
        "stateCid",
        "completedFaceCid",
    },
    "loop-outward-halted-face": {
        "kind",
        "schemaVersion",
        "targetCid",
        "effectCid",
        "guardFormulaCid",
        "stateCid",
        "outwardHaltedFaceCid",
    },
    "loop-binder-transform": {
        "kind",
        "schemaVersion",
        "targetCid",
        "inputStateCid",
        "elementValueCid",
        "outputStateCid",
        "binderPatternConstructionCid",
        "binderTransformCid",
    },
    "loop-body-transform": {
        "kind",
        "schemaVersion",
        "targetCid",
        "inputStateCid",
        "binderTransformCid",
        "bodySourceFragmentCid",
        "bodyExitTemplateCid",
        "bodyTransformCid",
    },
    "loop-test-transform": {
        "kind",
        "schemaVersion",
        "targetCid",
        "inputStateCid",
        "testValueConstructionCid",
        "trueGuardFormulaCid",
        "falseGuardFormulaCid",
        "haltedFaceCids",
        "testTransformCid",
    },
    "loop-iterator-testimony": {
        "kind",
        "schemaVersion",
        "targetCid",
        "iterableValueConstructionCid",
        "iteratorConstructionCid",
        "nextOperationCid",
        "exhaustionOperationCid",
        "iteratorTestimonyCid",
    },
    "for-operation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "nativeLoopTermCid",
        "binderTransformCid",
        "iteratorTestimonyCid",
        "operationCid",
    },
    "while-operation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "nativeLoopTermCid",
        "testTransformCid",
        "operationCid",
    },
    "loop-latch-obligation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "inputCompletedFaceCid",
        "inputStateCid",
        "operationKind",
        "successorTransformCid",
        "latchObligationCid",
    },
    "loop-continue-latch-obligation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "continueEffectCid",
        "inputHaltedFaceCid",
        "inputStateCid",
        "successorTransformCid",
        "continueLatchObligationCid",
    },
    "loop-break-exit-obligation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "breakEffectCid",
        "inputHaltedFaceCid",
        "outputCompletedFaceCid",
        "breakExitObligationCid",
    },
    "loop-exhaustion-exit-obligation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "operationTestimonyCid",
        "inputStateCid",
        "outputCompletedFaceCid",
        "exhaustionExitObligationCid",
    },
    "loop-else-exhaustion-obligation": {
        "kind",
        "schemaVersion",
        "targetCid",
        "inputCompletedFaceCid",
        "elseBodyTransformCid",
        "outputCompletedFaceCid",
        "elseExhaustionObligationCid",
    },
    "loop-post-binding": {
        "kind",
        "schemaVersion",
        "targetCid",
        "bindingCoordinateCid",
        "incomingStateCid",
        "completedFaceCid",
        "projectedStateCid",
        "postBindingObligationCid",
    },
}


@dataclass(frozen=True)
class LoopRecordV1:
    kind: str
    cid: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class LoopCompletedFaceV1:
    completion_kind: str
    state_cid: str
    cid: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class LoopOperationV1:
    kind: str
    cid: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class LoopConstructionV1:
    target: LoopTargetCoordinateV1
    pre_state: BindingStateV1
    operation: LoopOperationV1
    completed_faces: tuple[LoopCompletedFaceV1, ...]
    loop_construction_cid: str
    _graph: dict[str, Any]

    def wire_graph(self) -> dict[str, Any]:
        return deepcopy(self._graph)

    # ------------------------------------------------------------------
    # The authenticated native identity of this constructed value.
    #
    # ``_graph`` is an ALREADY-SEALED wire document: its root is a Merkle root
    # whose every field is either a scalar or the CID of a record in the store,
    # and ``loop_construction_cid`` is ``hash(root minus its own CID field)`` --
    # exactly what ``_validate_seal`` checks on decode. So this pair
    # (``preimage``, ``cid``) is self-authenticating and covers the COMPLETE
    # semantic content: ``target``, ``pre_state``, ``operation`` and
    # ``completed_faces`` are the decoded forms of the very CIDs the root binds.
    #
    # Declaring it is what lets ConstructedValueV2 reference this value by its
    # VALIDATED native CID instead of walking the raw wire document. Without
    # the declaration, ``_graph`` is a bare ``dict`` holding bare ``list``s --
    # mutable containers with no content coordinate, which ConstructedValueV2
    # correctly refuses to snapshot and reports as a typed gap.
    # ------------------------------------------------------------------
    @property
    def preimage(self) -> dict[str, Any]:
        """The preimage ``loop_construction_cid`` is the hash of."""
        return {
            key: value
            for key, value in self._graph["root"].items()
            if key != "loopConstructionCid"
        }

    @property
    def cid(self) -> str:
        """This construction's authenticated native CID."""
        return self.loop_construction_cid


def _decode_record(raw: Any) -> LoopRecordV1:
    if not isinstance(raw, dict):
        raise LoopWireError("malformed loop graph record")
    kind = raw.get("kind")
    if kind not in _RECORD_CID_FIELDS:
        raise LoopWireError(f"unknown loop record kind: {kind!r}")
    _exact(raw, _EXACT_FIELDS[kind], kind)
    if raw["schemaVersion"] != "1":
        raise LoopWireError(f"unsupported {kind}")
    cid = _validate_seal(raw, _RECORD_CID_FIELDS[kind], kind)
    for field, value in raw.items():
        if field.endswith("Cid") and field != _RECORD_CID_FIELDS[kind]:
            _require_cid(value, field)
        elif field.endswith("Cids"):
            if not isinstance(value, list):
                raise LoopWireError(f"{field} must be an array")
            for item in value:
                _require_cid(item, field)
    if kind == "loop-completed-face" and raw["completionKind"] not in {
        "BodyFallthrough",
        "NormalExhaustion",
        "BreakExit",
    }:
        raise LoopWireError("unknown loop completion kind")
    if kind == "loop-latch-obligation" and raw["operationKind"] not in {
        "ForNext",
        "WhileTest",
    }:
        raise LoopWireError("unknown latch operation")
    return LoopRecordV1(kind, cid, deepcopy(raw))


def _root(raw: Any) -> dict[str, Any]:
    fields = {
        "kind",
        "schemaVersion",
        "target",
        "preStateCid",
        "operation",
        "bodyTransformCid",
        "bodyExitTemplateCid",
        "latchObligationCids",
        "continueLatchObligationCids",
        "breakExitObligationCids",
        "exhaustionExitObligationCid",
        "elseBodyCid",
        "elseExhaustionObligationCid",
        "completedFaceCids",
        "outwardHaltedFaceCids",
        "postBindingObligationCids",
        "loopConstructionCid",
    }
    raw = _exact(raw, fields, "LoopConstructionV1")
    if raw["kind"] != "loop-construction" or raw["schemaVersion"] != "1":
        raise LoopWireError("unsupported LoopConstructionV1")
    for field in (
        "preStateCid",
        "bodyTransformCid",
        "bodyExitTemplateCid",
        "exhaustionExitObligationCid",
    ):
        _require_cid(raw[field], field)
    if raw["elseBodyCid"] is not None:
        _require_cid(raw["elseBodyCid"], "elseBodyCid")
    if raw["elseExhaustionObligationCid"] is not None:
        _require_cid(raw["elseExhaustionObligationCid"], "elseExhaustionObligationCid")
    if (raw["elseBodyCid"] is None) != (raw["elseExhaustionObligationCid"] is None):
        raise LoopWireError("else body and exhaustion obligation must appear together")
    for field in (
        "latchObligationCids",
        "continueLatchObligationCids",
        "breakExitObligationCids",
        "completedFaceCids",
        "outwardHaltedFaceCids",
        "postBindingObligationCids",
    ):
        if not isinstance(raw[field], list):
            raise LoopWireError(f"{field} must be an array")
        for cid in raw[field]:
            _require_cid(cid, field)
    _validate_seal(raw, "loopConstructionCid", "LoopConstructionV1")
    return raw


def decode_loop_construction_v1(graph: Any) -> LoopConstructionV1:
    graph = _exact(graph, {"root", "records"}, "LoopConstructionV1 graph")
    if not isinstance(graph["records"], list):
        raise LoopWireError("LoopConstructionV1 records must be an array")
    root = _root(graph["root"])
    target = decode_loop_target_coordinate_v1(root["target"])
    target_cid = target.target_cid

    states: dict[str, BindingStateV1] = {}
    records: dict[str, LoopRecordV1] = {}
    for raw in graph["records"]:
        if isinstance(raw, dict) and raw.get("kind") == "binding-state":
            state = decode_binding_state_v1(raw)
            if state.state_cid in states or state.state_cid in records:
                raise LoopWireError("duplicate loop graph CID")
            states[state.state_cid] = state
        else:
            record = _decode_record(raw)
            if record.cid in states or record.cid in records:
                raise LoopWireError("duplicate loop graph CID")
            records[record.cid] = record

    def state(cid: str) -> BindingStateV1:
        try:
            return states[cid]
        except KeyError as exc:
            raise LoopWireError(f"missing binding-state {cid}") from exc

    def record(cid: str, kind: str | None = None) -> LoopRecordV1:
        try:
            found = records[cid]
        except KeyError as exc:
            raise LoopWireError(f"missing loop record {cid}") from exc
        if kind is not None and found.kind != kind:
            raise LoopWireError(f"loop record {cid} is not {kind}")
        return found

    pre_state = state(root["preStateCid"])
    operation_raw = root["operation"]
    if not isinstance(operation_raw, dict) or operation_raw.get("kind") not in {
        "for-operation",
        "while-operation",
    }:
        raise LoopWireError("unknown loop operation")
    operation_record = _decode_record(operation_raw)
    if operation_record.raw["targetCid"] != target_cid:
        raise LoopWireError("operation target mismatch")
    operation = LoopOperationV1(
        operation_record.kind, operation_record.cid, operation_record.raw
    )
    body = record(root["bodyTransformCid"], "loop-body-transform")
    if body.raw["targetCid"] != target_cid:
        raise LoopWireError("body target mismatch")
    state(body.raw["inputStateCid"])

    if operation.kind == "for-operation":
        record(operation.raw["binderTransformCid"], "loop-binder-transform")
        record(operation.raw["iteratorTestimonyCid"], "loop-iterator-testimony")
    else:
        record(operation.raw["testTransformCid"], "loop-test-transform")

    completed = []
    completed_by_cid = {}
    for cid in root["completedFaceCids"]:
        face = record(cid, "loop-completed-face")
        if face.raw["targetCid"] != target_cid:
            raise LoopWireError("completed face target mismatch")
        state(face.raw["stateCid"])
        decoded = LoopCompletedFaceV1(
            face.raw["completionKind"], face.raw["stateCid"], face.cid, face.raw
        )
        completed.append(decoded)
        completed_by_cid[cid] = decoded

    for cid in root["latchObligationCids"]:
        latch = record(cid, "loop-latch-obligation")
        if latch.raw["targetCid"] != target_cid:
            raise LoopWireError("latch target mismatch")
        state(latch.raw["inputStateCid"])
        input_face = completed_by_cid.get(latch.raw["inputCompletedFaceCid"])
        if input_face is None or input_face.completion_kind != "BodyFallthrough":
            raise LoopWireError("latch input must be BodyFallthrough")
        record(latch.raw["successorTransformCid"])

    for cid in root["continueLatchObligationCids"]:
        latch = record(cid, "loop-continue-latch-obligation")
        if latch.raw["targetCid"] != target_cid:
            raise LoopWireError("continue latch target mismatch")
        state(latch.raw["inputStateCid"])
        record(latch.raw["successorTransformCid"])

    for cid in root["breakExitObligationCids"]:
        obligation = record(cid, "loop-break-exit-obligation")
        if obligation.raw["targetCid"] != target_cid:
            raise LoopWireError("break obligation target mismatch")
        output = completed_by_cid.get(obligation.raw["outputCompletedFaceCid"])
        if output is None or output.completion_kind != "BreakExit":
            raise LoopWireError("break obligation must output BreakExit")

    exhaustion = record(
        root["exhaustionExitObligationCid"], "loop-exhaustion-exit-obligation"
    )
    if exhaustion.raw["targetCid"] != target_cid:
        raise LoopWireError("exhaustion obligation target mismatch")
    state(exhaustion.raw["inputStateCid"])
    output = completed_by_cid.get(exhaustion.raw["outputCompletedFaceCid"])
    if output is None or output.completion_kind != "NormalExhaustion":
        raise LoopWireError("exhaustion obligation must output NormalExhaustion")

    if root["elseExhaustionObligationCid"] is not None:
        else_obligation = record(
            root["elseExhaustionObligationCid"],
            "loop-else-exhaustion-obligation",
        )
        incoming = completed_by_cid.get(else_obligation.raw["inputCompletedFaceCid"])
        if incoming is None or incoming.completion_kind != "NormalExhaustion":
            raise LoopWireError("else input must be NormalExhaustion")
        if else_obligation.raw["elseBodyTransformCid"] != root["elseBodyCid"]:
            raise LoopWireError("else body transform mismatch")
        if else_obligation.raw["outputCompletedFaceCid"] not in completed_by_cid:
            raise LoopWireError("else output is not a completed face")

    for cid in root["postBindingObligationCids"]:
        post = record(cid, "loop-post-binding")
        if post.raw["targetCid"] != target_cid:
            raise LoopWireError("post binding target mismatch")
        state(post.raw["incomingStateCid"])
        state(post.raw["projectedStateCid"])
        if post.raw["completedFaceCid"] not in completed_by_cid:
            raise LoopWireError("post binding face is not completed")

    for cid in root["outwardHaltedFaceCids"]:
        halted = record(cid, "loop-outward-halted-face")
        if halted.raw["targetCid"] != target_cid:
            raise LoopWireError("outward halted target mismatch")
        state(halted.raw["stateCid"])

    return LoopConstructionV1(
        target,
        pre_state,
        operation,
        tuple(completed),
        root["loopConstructionCid"],
        deepcopy(graph),
    )


__all__ = [
    "BindingStateV1",
    "LoopConstructionV1",
    "LoopTargetCoordinateV1",
    "LoopWireError",
    "decode_binding_state_v1",
    "decode_loop_construction_v1",
    "decode_loop_target_coordinate_v1",
    "mint_loop_target_coordinate_v1",
    "seal_loop_record",
    "seal_binding_state_v1",
]
