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


@dataclass(frozen=True)
class OpaqueSourceCallObligationV1:
    """Authenticated unresolved callee testimony parked at one source call."""

    coordinate: SourceFragmentCoordinateV1
    target_name: str
    resolved_object_cid: str
    resolution_kind: str = "opaque-call-target"


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

    def _first_boundary_semantics(self):
        from sugar_lift_py_tests.outcome import Completed

        for face in self.boundary_faces.exits:
            if isinstance(face, Completed):
                return face.value
        raise ValueError("factored boundary has no completed EffectBoundary face")

    @property
    def shared_expected_type_operand(self):
        """Expected-type operand shared by every message-pattern face."""
        return self._first_boundary_semantics().expected_type_operand

    @property
    def shared_binding(self):
        """Binding declaration shared by every message-pattern face."""
        return self._first_boundary_semantics().binding


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


def _gap_kinds() -> frozenset[str]:
    """The closed resolution-gap vocabulary, read from its ONE owner.

    This used to be a second hand-maintained copy of ten members, and it drifted:
    the source-derived path minted fused ``kind:detail`` strings that this very
    decoder would have refused as ``malformed context-manager resolution gap``.
    Two lists cannot disagree if there is only one list, so the members come
    from :class:`WithConstructionGapKind`, which the producers' own typed
    ``Literal``s are declared against.

    Imported lazily: ``sugar_source_tree`` depends on this module.
    """
    from sugar_source_tree.panic import WithConstructionGapKind

    return frozenset(
        member.value
        for member in WithConstructionGapKind
        # The catch-all is a READER's fallback for a kind this build does not
        # name; no producer may emit it as a gap kind of its own.
        if member is not WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND
    )


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
            if not isinstance(gap, dict) or gap.get("kind") not in _gap_kinds():
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
