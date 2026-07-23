"""Frozen, authenticated context-manager coordinates installed before construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
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
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    target_symbol: str | None
    kind: str
    candidate_member_cids: tuple[str, ...]


ContextManagerResolutionV1 = ContextManagerContractRefV1 | ContextManagerResolutionGapV1


@dataclass(frozen=True)
class SourceDerivedContextManagerRefV1:
    """Live protocol testimony plus its immutable h=h(p) summary coordinate."""

    use_site: SourceFragmentCoordinateV1
    summary_cid: str
    semantics: ContextManagerSemanticsV1
    import_signature: ImportSignatureV2
    protocol: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class ResolvedContractRefsV1:
    catalog_cid: str
    table_cid: str
    by_use_site: Mapping[SourceFragmentCoordinateV1, ContextManagerResolutionV1]

    def require(
        self, use_site: SourceFragmentCoordinateV1
    ) -> ContextManagerResolutionV1:
        try:
            return self.by_use_site[use_site]
        except KeyError as exc:
            raise ContractRefProtocolError(
                "BackendDefect: enrolled context-manager demand missing from resolution table"
            ) from exc


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
    source_derived_contract_refs: dict = field(default_factory=dict)
    # Runtime-only, prebound class-base Sugar children keyed by the exact
    # subclass definition coordinate.  These are never serialized; the class
    # definition projects their sealed CIDs into its own preimage.
    source_class_bases: dict = field(default_factory=dict)
    # Source-call frame construction deliberately has no CM enrollment pass.
    # Its nested With nodes must remain capability-loud, not accuse a missing
    # row in a table that this context never claimed to populate.
    contract_enrollment_required: bool = True

    @classmethod
    def for_source_call_construction(
        cls,
        *,
        source_call_frames: dict | None = None,
        call_contract_refs: object | None = None,
        workspace_root: str | None = None,
    ) -> "TreeConstructionContextV1":
        """Construction context for sole-path source-call frames without CM enrollment."""
        return cls(
            contract_refs=empty_resolved_contract_refs(),
            call_contract_refs=call_contract_refs,
            workspace_root=workspace_root,
            source_call_frames={} if source_call_frames is None else source_call_frames,
            contract_enrollment_required=False,
        )


_GAP_KINDS = frozenset(
    {
        "runtime-selected",
        "unresolved-symbol",
        "ambiguous-symbol",
        "wrong-contract-kind",
        "signature-mismatch",
        "unauthenticated-member",
        "payload-cid-mismatch",
        "unsupported-cm-schema",
        "no-derived-contract",
        "stale-derived-contract",
    }
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
            if not isinstance(gap, dict) or gap.get("kind") not in _GAP_KINDS:
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
