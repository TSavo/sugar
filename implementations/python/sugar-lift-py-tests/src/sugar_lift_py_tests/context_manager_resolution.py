"""Frozen, authenticated context-manager coordinates installed before construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from enum import Enum
from typing import Any, Mapping

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import (
    ContextManagerContractError,
    ContextManagerSemanticsV1,
    ImportSignatureV2,
    decode_context_manager_semantics_v1,
    decode_import_signature_v2,
    _json_value,
)
from .ir import Sort


class ContractRefProtocolError(ValueError):
    pass


class NativeProtocolSlot(str, Enum):
    """Closed source protocol slots, independent of vendor member spelling."""

    CONTEXT_ENTER = "context-enter"
    CONTEXT_EXIT = "context-exit"
    TRUTH = "truth"
    SET_ITEM = "set-item"
    GET_ITEM = "get-item"


@dataclass(frozen=True, order=True)
class SourceFragmentCoordinateV1:
    source_cid: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def decode(cls, raw: Any) -> "SourceFragmentCoordinateV1":
        if not isinstance(raw, dict) or set(raw) != {
            "sourceCid",
            "startLine",
            "startCol",
            "endLine",
            "endCol",
        }:
            raise ContractRefProtocolError("malformed source-fragment coordinate")
        values = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        if not isinstance(raw["sourceCid"], str) or not all(
            isinstance(value, int) and value >= 0 for value in values
        ):
            raise ContractRefProtocolError(
                "malformed source-fragment coordinate fields"
            )
        return cls(raw["sourceCid"], *values)

    def wire(self) -> dict[str, Any]:
        return {
            "sourceCid": self.source_cid,
            "startLine": self.start_line,
            "startCol": self.start_col,
            "endLine": self.end_line,
            "endCol": self.end_col,
        }

    @property
    def cid(self) -> str:
        """Canonical CID of this owner's existing wire representation."""
        from sugar_lift_python_source.canonical import cid_of_json

        return cid_of_json(self.wire())


_IMPORT_CALL_VALUE_SUBSUMPTION_AUTHORITY = object()


@dataclass(frozen=True)
class ImportedCallValueSubsumptionV1:
    source_cid: str
    module_identity_cid: str
    import_binding_cid: str
    target_symbol: str
    exported_member_path: tuple[str, ...]
    call_coordinate: SourceFragmentCoordinateV1
    callee_coordinate: SourceFragmentCoordinateV1
    call_use_cid: str
    value_use_cid: str
    resolution_kind: str
    resolved_object_cid: str
    relation_cid: str
    _authority: object = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._authority is not _IMPORT_CALL_VALUE_SUBSUMPTION_AUTHORITY:
            raise ValueError("import call/value subsumption lacks producer authority")
        if (
            not all(
                (
                    self.source_cid,
                    self.module_identity_cid,
                    self.import_binding_cid,
                    self.target_symbol,
                    self.call_use_cid,
                    self.value_use_cid,
                    self.resolution_kind,
                    self.resolved_object_cid,
                    self.relation_cid,
                )
            )
            or not self.exported_member_path
        ):
            raise ValueError("import call/value subsumption lacks binding testimony")
        if (
            self.call_coordinate.source_cid != self.source_cid
            or self.callee_coordinate.source_cid != self.source_cid
        ):
            raise ValueError("import call/value subsumption crosses source identity")
        if (
            self.call_coordinate.start_line,
            self.call_coordinate.start_col,
        ) != (
            self.callee_coordinate.start_line,
            self.callee_coordinate.start_col,
        ) or (
            self.call_coordinate.end_line,
            self.call_coordinate.end_col,
        ) < (
            self.callee_coordinate.end_line,
            self.callee_coordinate.end_col,
        ):
            raise ValueError("import call/value subsumption has unrelated occurrences")
        if self.relation_cid != self._expected_cid():
            raise ValueError("import call/value subsumption CID is stale")

    def _expected_cid(self) -> str:
        from sugar_lift_python_source.canonical import cid_of_json

        return cid_of_json(
            {
                "schemaVersion": 1,
                "kind": "imported-call-value-subsumption",
                "sourceCid": self.source_cid,
                "moduleIdentityCid": self.module_identity_cid,
                "importBindingCid": self.import_binding_cid,
                "targetSymbol": self.target_symbol,
                "exportedMemberPath": list(self.exported_member_path),
                "callCoordinate": self.call_coordinate.wire(),
                "calleeCoordinate": self.callee_coordinate.wire(),
                "callUseCid": self.call_use_cid,
                "valueUseCid": self.value_use_cid,
                "resolutionKind": self.resolution_kind,
                "resolvedObjectCid": self.resolved_object_cid,
            }
        )


def _mint_import_call_value_subsumption(
    *,
    call_receipt,
    value_receipt,
    call_coordinate: SourceFragmentCoordinateV1,
    callee_coordinate: SourceFragmentCoordinateV1,
    resolution_kind: str,
    resolved_object_cid: str,
) -> ImportedCallValueSubsumptionV1:
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1
    from sugar_lift_python_source.canonical import cid_of_json

    if (
        type(call_receipt) is not AuthenticatedImportUseV1
        or type(value_receipt) is not AuthenticatedImportUseV1
    ):
        raise ValueError("import call/value subsumption requires exact receipts")
    call_receipt.revalidate()
    value_receipt.revalidate()
    exported = tuple(value_receipt.use["exportedMemberPath"])
    call_site = call_receipt.use["useSite"]
    value_site = value_receipt.use["useSite"]
    if (
        call_receipt.demand.get("kind") != "call-contract-demand"
        or value_receipt.demand.get("kind") != "import-value-use-demand"
        or value_receipt.use.get("role") != "value-use"
        or value_receipt.demand.get("role") != "value-use"
        or call_receipt.source_cid != value_receipt.source_cid
        or call_receipt.target_symbol != value_receipt.target_symbol
        or call_receipt.import_binding.cid != value_receipt.import_binding.cid
        or call_coordinate.source_cid != call_receipt.source_cid
        or callee_coordinate.source_cid != value_receipt.source_cid
        or (
            call_coordinate.start_line,
            call_coordinate.start_col,
            call_coordinate.end_line,
            call_coordinate.end_col,
        )
        != (
            call_site["startLine"],
            call_site["startCol"],
            call_site["endLine"],
            call_site["endCol"],
        )
        or callee_coordinate.wire() != value_site
    ):
        raise ValueError("import call/value subsumption receipts are cross-wired")
    module_identity = call_receipt.import_binding.value["target"]["moduleIdentity"]
    relation = object.__new__(ImportedCallValueSubsumptionV1)
    values = {
        "source_cid": call_receipt.source_cid,
        "module_identity_cid": cid_of_json(module_identity),
        "import_binding_cid": call_receipt.import_binding.cid,
        "target_symbol": call_receipt.target_symbol,
        "exported_member_path": exported,
        "call_coordinate": call_coordinate,
        "callee_coordinate": callee_coordinate,
        "call_use_cid": call_receipt.use["cid"],
        "value_use_cid": value_receipt.use["cid"],
        "resolution_kind": resolution_kind,
        "resolved_object_cid": resolved_object_cid,
    }
    for name, value in values.items():
        object.__setattr__(relation, name, value)
    object.__setattr__(relation, "relation_cid", relation._expected_cid())
    object.__setattr__(relation, "_authority", _IMPORT_CALL_VALUE_SUBSUMPTION_AUTHORITY)
    relation.__post_init__()
    return relation


@dataclass(frozen=True)
class OpaqueSourceCallObligationV1:
    """Authenticated unresolved callee testimony parked at one source call."""

    coordinate: SourceFragmentCoordinateV1
    target_name: str
    resolved_object_cid: str
    resolution_kind: str = "opaque-call-target"
    import_call_value_subsumption: ImportedCallValueSubsumptionV1 | None = None

    def __post_init__(self) -> None:
        relation = self.import_call_value_subsumption
        if relation is None:
            return
        if type(relation) is not ImportedCallValueSubsumptionV1:
            raise ValueError("opaque call has malformed import subsumption")
        if (
            relation.call_coordinate != self.coordinate
            or relation.target_symbol != self.target_name
            or relation.resolution_kind != self.resolution_kind
            or relation.resolved_object_cid != self.resolved_object_cid
        ):
            raise ValueError("opaque call/subsumption testimony is cross-wired")


@dataclass(frozen=True)
class ContextManagerContractRefV1:
    resolution_cid: str
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    use_site_cid: str
    authenticated_import_use_cid: str
    import_binding_cid: str
    construction_context_generation_cid: str
    contract_cid: str
    payload_cid: str
    provenance_cid: str
    distribution_artifact_cid: str
    dependency_artifact_graph_cid: str
    module_source_cid: str
    resolved_definition_cid: str
    manager_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    import_signature: ImportSignatureV2
    semantics: ContextManagerSemanticsV1


@dataclass(frozen=True)
class ContextManagerResolutionGapV1:
    """One unresolved context-manager demand: a structural kind beside its data.

    ``kind`` is the STRUCTURAL key and nothing else -- a member of the closed
    vocabulary in :func:`_gap_kinds`.  It never contains a symbol.  The
    derivation layer used to fuse ``f"{kind}:{detail}"`` into this field, which
    put most of the pinned-pandas resolution board's mass under a vendor spelling
    (#6371) and produced, in process, a gap this module's own decoder would
    refuse.

    ``target_symbol`` and ``detail`` are DATA: they ride the row for a human
    reading one row, and are never a bucket key.  A measurement a vendor rename
    can move is not a measurement.

    Unresolved demand after derivation: construct the contract or panic.
    """

    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    target_symbol: str | None
    kind: str
    candidate_member_cids: tuple[str, ...]
    # In-process only.  Not read from or written to the wire, so no preimage
    # and no CID changes: the authenticated table hashes the bytes present.
    detail: str | None = None


ContextManagerResolutionV1 = ContextManagerContractRefV1 | ContextManagerResolutionGapV1


@dataclass(frozen=True)
class NativeDefinitionCoordinateGapV1:
    receiver: SourceFragmentCoordinateV1
    slot: NativeProtocolSlot
    reason: str


NativeDefinitionCoordinateResolutionV1 = (
    SourceFragmentCoordinateV1 | NativeDefinitionCoordinateGapV1
)


@dataclass(frozen=True)
class SourceDerivedContextManagerRefV1:
    """Live protocol testimony plus its immutable h=h(p) summary coordinate."""

    use_site: SourceFragmentCoordinateV1
    summary_cid: str
    semantics: ContextManagerSemanticsV1
    import_signature: ImportSignatureV2
    protocol: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class SourceDerivedGeneratorResourceRefV1:
    """Closed source-derived resource contract for generator managers.

    Requires authenticated generator lifecycle (source-visible frame with
    ``generator_steps``) plus native enter/exit definition coordinates.
    Coordinates alone cannot construct this ref; a non-generator frame cannot
    acquire generator semantics. Protocol is generator-backed testimony, never
    a fabricated ObjectValue receiver.

    ONE typed surface for consumers: :meth:`generator_protocol` (and the
    definition accessors) expose enter/exit definitions and lifecycle
    performance without branching on Lifecycle-vs-Manager wrapper classes.
    """

    use_site: SourceFragmentCoordinateV1
    summary_cid: str
    semantics: ContextManagerSemanticsV1
    import_signature: ImportSignatureV2
    protocol: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        protocol = self.protocol
        if protocol is None:
            raise ValueError(
                "generator resource ref requires generator-backed protocol testimony"
            )
        frame = getattr(protocol, "generator_frame", None)
        if frame is None or getattr(frame, "generator_steps", None) is None:
            raise ValueError(
                "generator resource ref refuses non-generator protocol testimony"
            )
        if getattr(protocol, "enter_definition", None) is None:
            raise ValueError("generator resource ref requires enter definition")
        if getattr(protocol, "exit_definition", None) is None:
            raise ValueError("generator resource ref requires exit definition")
        if protocol.enter_definition == protocol.exit_definition:
            raise ValueError("generator enter/exit definitions must differ")
        # Closed performance surface: enter/exit must be methods, not missing.
        if not callable(getattr(protocol, "enter_resource_outcome", None)):
            raise ValueError(
                "generator resource ref requires enter_resource_outcome on protocol"
            )
        if not callable(getattr(protocol, "exit_outcome_for", None)):
            raise ValueError(
                "generator resource ref requires exit_outcome_for on protocol"
            )

    @property
    def generator_protocol(self):
        """The one closed protocol surface published on this ref.

        Always the generator-backed protocol (base or lifecycle subclass of
        it). Consumers rebase onto this property — never enumerate wrapper
        class names for enter/exit definitions or lifecycle performance.
        """
        return self.protocol

    @property
    def enter_definition(self):
        """Native enter definition coordinate from the closed protocol surface."""
        return self.protocol.enter_definition

    @property
    def exit_definition(self):
        """Native exit definition coordinate from the closed protocol surface."""
        return self.protocol.exit_definition

    @property
    def protocol_construction_cid(self) -> str:
        """Protocol construction CID from the closed protocol surface."""
        return self.protocol.protocol_construction_cid


@dataclass(frozen=True)
class FactoredSourceDerivedContextManagerRefV1:
    """Source-derived EffectBoundary with factored message-pattern faces.

    Undecided ``match`` stays partitioned as guarded alternatives:

    - ``match=None`` → ``NoMessagePatternV1``
    - ``match=pattern`` → pattern obligation

    ``boundary_faces`` is an ``ExitSet`` of ``EffectBoundarySemanticsV1`` under
    face guards. Faces are never recombined into one sealed summary CID and
    never collapsed into a generic ``no-derived-contract`` gap.
    """

    use_site: SourceFragmentCoordinateV1
    protocol_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    boundary_faces: object
    import_signature: ImportSignatureV2
    protocol: object = field(compare=False, repr=False)

    def _completed_boundary_semantics(self):
        from sugar_lift_py_tests.outcome import Completed

        return tuple(
            face.value
            for face in self.boundary_faces.exits
            if isinstance(face, Completed)
        )

    def _shared_authority_field(self, field_name: str):
        """Authority shared by every face, or refuse when faces disagree.

        Expected-type and binding testimony authorize ALL message-pattern faces
        (nodes.py observation slot / exception authentication). Face zero must
        never speak for a sibling with different testimony.
        """
        from sugar_source_tree.panic import SugarNotWritten

        faces = self._completed_boundary_semantics()
        if not faces:
            raise ValueError("factored boundary has no completed EffectBoundary face")
        values = tuple(getattr(face, field_name) for face in faces)
        first = values[0]
        if any(value != first for value in values[1:]):
            observed = ", ".join(
                f"{type(value).__name__}={value!r}" for value in values
            )
            raise SugarNotWritten(
                blame=self.use_site,
                owner=f"FactoredSourceDerivedContextManagerRefV1.shared_{field_name}",
                observed=(
                    f"factored EffectBoundary faces disagree on {field_name}: "
                    f"{observed}"
                ),
                requested=(
                    f"identical {field_name} testimony on every completed "
                    "message-pattern face"
                ),
                fix=(
                    "never authorize all faces from the first completed face when "
                    "expected-type or binding testimony differs; keep the "
                    "disagreement loud"
                ),
            )
        return first

    @property
    def shared_expected_type_operand(self):
        """Expected-type operand shared by every message-pattern face."""
        return self._shared_authority_field("expected_type_operand")

    @property
    def shared_binding(self):
        """Binding declaration shared by every message-pattern face."""
        return self._shared_authority_field("binding")


@dataclass(frozen=True)
class ResolvedContractRefsV1:
    catalog_cid: str
    table_cid: str
    by_use_site: Mapping[SourceFragmentCoordinateV1, ContextManagerResolutionV1]
    native_definitions: Mapping[
        tuple[SourceFragmentCoordinateV1, NativeProtocolSlot],
        NativeDefinitionCoordinateResolutionV1,
    ] = field(default_factory=dict)

    def require(
        self, use_site: SourceFragmentCoordinateV1
    ) -> ContextManagerResolutionV1:
        try:
            return self.by_use_site[use_site]
        except KeyError as exc:
            raise ContractRefProtocolError(
                "BackendDefect: enrolled context-manager demand missing from resolution table"
            ) from exc

    def require_native_definition(
        self, receiver: SourceFragmentCoordinateV1, slot: NativeProtocolSlot
    ) -> NativeDefinitionCoordinateResolutionV1:
        """Resolve one authenticated source definition, or retain UNDECIDED."""
        result = self.native_definitions.get((receiver, slot))
        if result is None:
            return NativeDefinitionCoordinateGapV1(
                receiver=receiver,
                slot=slot,
                reason="authenticated source definition coordinate is not enrolled",
            )
        return result


# Placeholder table for construction that does not enroll context-manager
# demands (e.g. sole-path manager-factory construction). With.require still
# fails closed when a use-site is absent.
_EMPTY_CONTRACT_TABLE_CID = "blake3-512:" + ("00" * 64)


def empty_resolved_contract_refs() -> ResolvedContractRefsV1:
    from types import MappingProxyType

    return ResolvedContractRefsV1(
        catalog_cid=_EMPTY_CONTRACT_TABLE_CID,
        table_cid=_EMPTY_CONTRACT_TABLE_CID,
        by_use_site=MappingProxyType({}),
    )


@dataclass(frozen=True)
class TreeConstructionContextV1:
    """Explicit tree construction handle — the only non-Sugar construction currency.

    - ``contract_refs``: prebound With resolutions (empty table is valid; missing
      use-sites stay loud via ``require``).
    - ``source_call_frames``: prebound ordinary source-call frames keyed by
      use-site coordinate string; mutated only by the sole-path scheduler that
      owns the handle, never ambient process state.
    """

    contract_refs: ResolvedContractRefsV1
    call_contract_refs: object | None = None
    workspace_root: str | None = None
    # Mutable frame table held by reference; the context object itself is frozen.
    source_call_frames: dict = field(default_factory=dict)
    # Closed source-call preconstruction rows at exact use sites.  A frame is
    # installed only beside a successful authenticated row; every other row is
    # a typed loud classification consumed by census/linking.
    source_call_resolutions: dict = field(default_factory=dict)
    # Unresolved named calls parked at exact source coordinates. Ordinary Sugar
    # construction consumes the testimony only when execution reaches the call.
    opaque_source_call_obligations: dict = field(default_factory=dict)
    source_derived_contract_refs: dict = field(default_factory=dict)
    # Reaching provider Calls for bare-Name manager uses, keyed by the immutable
    # manager-use coordinate.  Binding coordinates own identity: the Name at the
    # With head is not the provider; this table seats the authenticated Call
    # that the Name reaches so With construction never re-resolves by spelling.
    source_manager_provider_calls: dict = field(default_factory=dict)
    # Runtime-only, prebound class-base Sugar children keyed by the exact
    # subclass definition coordinate.  These are never serialized; the class
    # definition projects their sealed CIDs into its own preimage.
    source_class_bases: dict = field(default_factory=dict)
    # Final-checked import *value-use* resolutions seated at exact use sites
    # of the frame's own SourceUnit (source_cid-matched).  Never carries
    # cross-unit spans; keyed by SourceFragmentCoordinateV1 of this unit.
    source_import_value_resolutions: dict = field(default_factory=dict)
    # Producer-minted value-use receipt roster, retained once per exact source
    # CID so repeated frame/class publication transports object identity rather
    # than reminting an equivalent receipt at an occupied SourceUnit seat.
    source_import_value_receipts: dict = field(default_factory=dict)
    # Exact module-seat/use-occurrence transport shared by parser-owned units
    # in this construction only. Never global and never source-CID-only.
    source_import_value_receipts_by_site: dict = field(default_factory=dict)
    # When projecting an authenticated definition into a call frame, dual-mode
    # factory bodies may contain With sites only on non-manager return paths
    # (e.g. pytest.raises function form). Soft projection does not require
    # those nested Withs to already carry a closed CM row — the CM form's
    # return path is what construct_manager_behavior force_floors.
    frame_projection: bool = False

    @classmethod
    def for_source_call_construction(
        cls,
        *,
        source_call_frames: dict | None = None,
        opaque_source_call_obligations: dict | None = None,
        call_contract_refs: object | None = None,
        workspace_root: str | None = None,
        frame_projection: bool = False,
    ) -> "TreeConstructionContextV1":
        """Construction context for sole-path source-call frames without CM enrollment."""
        return cls(
            contract_refs=empty_resolved_contract_refs(),
            call_contract_refs=call_contract_refs,
            workspace_root=workspace_root,
            source_call_frames={} if source_call_frames is None else source_call_frames,
            frame_projection=frame_projection,
            opaque_source_call_obligations=(
                {}
                if opaque_source_call_obligations is None
                else opaque_source_call_obligations
            ),
        )


def _gap_kinds() -> None:
    """Deleted closed taxonomy. Kinds are free structural keys, not a census enum."""
    return None


def _cid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise ContractRefProtocolError(f"{field} must be a CID")
    return value


def _decode_signature(raw: Any) -> ImportSignatureV2:
    try:
        return decode_import_signature_v2(raw)
    except ContextManagerContractError as exc:
        raise ContractRefProtocolError("malformed ImportSignatureV2") from exc


def _resolution_cid_preimage(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: raw[key]
        for key in (
            "schemaVersion",
            "demandCid",
            "useSite",
            "useSiteCid",
            "authenticatedImportUseCid",
            "importBindingCid",
            "constructionContextGenerationCid",
            "contractCid",
            "payloadCid",
            "provenanceCid",
            "distributionArtifactCid",
            "dependencyArtifactGraphCid",
            "moduleSourceCid",
            "resolvedDefinitionCid",
            "managerConstructionCid",
            "enterTestimonyCid",
            "exitTestimonyCid",
            "importSignature",
            "semantics",
        )
    }


def _hash_json(raw: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(raw)).encode("utf-8"))


def _decode_ref(raw: Any) -> ContextManagerContractRefV1:
    expected = {
        "kind",
        "schemaVersion",
        "resolutionCid",
        "demandCid",
        "useSite",
        "useSiteCid",
        "authenticatedImportUseCid",
        "importBindingCid",
        "constructionContextGenerationCid",
        "contractCid",
        "payloadCid",
        "provenanceCid",
        "distributionArtifactCid",
        "dependencyArtifactGraphCid",
        "moduleSourceCid",
        "resolvedDefinitionCid",
        "managerConstructionCid",
        "enterTestimonyCid",
        "exitTestimonyCid",
        "importSignature",
        "semantics",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ContractRefProtocolError("malformed context-manager contract ref")
    if raw["kind"] != "context-manager-contract-ref" or raw["schemaVersion"] != "1":
        raise ContractRefProtocolError("unsupported context-manager contract ref")
    resolution_cid = _cid(raw["resolutionCid"], "resolutionCid")
    if _hash_json(_resolution_cid_preimage(raw)) != resolution_cid:
        raise ContractRefProtocolError("resolution CID mismatch")
    try:
        signature = _decode_signature(raw["importSignature"])
        semantics = decode_context_manager_semantics_v1(raw["semantics"], signature)
    except ContextManagerContractError as exc:
        raise ContractRefProtocolError("unsupported context-manager semantics") from exc
    use_site = SourceFragmentCoordinateV1.decode(raw["useSite"])
    if _hash_json(use_site.wire()) != _cid(raw["useSiteCid"], "useSiteCid"):
        raise ContractRefProtocolError("use-site CID mismatch")
    return ContextManagerContractRefV1(
        resolution_cid,
        _cid(raw["demandCid"], "demandCid"),
        use_site,
        _cid(raw["useSiteCid"], "useSiteCid"),
        _cid(raw["authenticatedImportUseCid"], "authenticatedImportUseCid"),
        _cid(raw["importBindingCid"], "importBindingCid"),
        _cid(
            raw["constructionContextGenerationCid"], "constructionContextGenerationCid"
        ),
        _cid(raw["contractCid"], "contractCid"),
        _cid(raw["payloadCid"], "payloadCid"),
        _cid(raw["provenanceCid"], "provenanceCid"),
        _cid(raw["distributionArtifactCid"], "distributionArtifactCid"),
        _cid(raw["dependencyArtifactGraphCid"], "dependencyArtifactGraphCid"),
        _cid(raw["moduleSourceCid"], "moduleSourceCid"),
        _cid(raw["resolvedDefinitionCid"], "resolvedDefinitionCid"),
        _cid(raw["managerConstructionCid"], "managerConstructionCid"),
        _cid(raw["enterTestimonyCid"], "enterTestimonyCid"),
        _cid(raw["exitTestimonyCid"], "exitTestimonyCid"),
        signature,
        semantics,
    )


def decode_resolved_contract_refs(raw: Any) -> ResolvedContractRefsV1:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"kind", "schemaVersion", "catalogCid", "tableCid", "byUseSite"}
        or raw["kind"] != "resolved-contract-refs"
        or raw["schemaVersion"] != "1"
    ):
        raise ContractRefProtocolError("malformed resolved-contract-ref table")
    table_cid = _cid(raw["tableCid"], "tableCid")
    identity = {
        key: raw[key] for key in ("kind", "schemaVersion", "catalogCid", "byUseSite")
    }
    if _hash_json(identity) != table_cid:
        raise ContractRefProtocolError("resolution table CID mismatch")
    rows = raw["byUseSite"]
    if not isinstance(rows, list):
        raise ContractRefProtocolError("byUseSite must be a list")
    decoded: dict[SourceFragmentCoordinateV1, ContextManagerResolutionV1] = {}
    catalog_cid = _cid(raw["catalogCid"], "catalogCid")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"useSite", "resolution"}:
            raise ContractRefProtocolError("malformed resolution row")
        use_site = SourceFragmentCoordinateV1.decode(row["useSite"])
        resolution = row["resolution"]
        if not isinstance(resolution, dict):
            raise ContractRefProtocolError("malformed resolution")
        if resolution.get("kind") == "resolved" and set(resolution) == {
            "kind",
            "reference",
        }:
            value: ContextManagerResolutionV1 = _decode_ref(resolution["reference"])
            if value.use_site != use_site:
                raise ContractRefProtocolError("resolution coordinate mismatch")
        elif resolution.get("kind") == "unresolved" and set(resolution) == {
            "kind",
            "gap",
        }:
            gap = resolution["gap"]
            if not isinstance(gap, dict) or not isinstance(gap.get("kind"), str) or not gap.get("kind"):
                raise ContractRefProtocolError(
                    "malformed context-manager resolution gap"
                )
            candidates = gap.get("candidateMemberCids")
            if not isinstance(candidates, list) or candidates != sorted(candidates):
                raise ContractRefProtocolError("candidate member CIDs must be sorted")
            value = ContextManagerResolutionGapV1(
                _cid(gap.get("demandCid"), "demandCid"),
                SourceFragmentCoordinateV1.decode(gap.get("useSite")),
                gap.get("targetSymbol"),
                gap["kind"],
                tuple(_cid(v, "candidateMemberCid") for v in candidates),
            )
            if value.use_site != use_site:
                raise ContractRefProtocolError("gap coordinate mismatch")
        else:
            raise ContractRefProtocolError("unknown context-manager resolution")
        if use_site in decoded:
            raise ContractRefProtocolError("duplicate resolution coordinate")
        decoded[use_site] = value
    return ResolvedContractRefsV1(catalog_cid, table_cid, MappingProxyType(decoded))
