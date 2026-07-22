"""Frozen, authenticated context-manager coordinates installed before construction."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import (
    ContextManagerContractError,
    ContextManagerSemanticsV1,
    _decode_semantics,
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
            "sourceCid", "startLine", "startCol", "endLine", "endCol"
        }:
            raise ContractRefProtocolError("malformed source-fragment coordinate")
        values = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        if not isinstance(raw["sourceCid"], str) or not all(
            isinstance(value, int) and value >= 0 for value in values
        ):
            raise ContractRefProtocolError("malformed source-fragment coordinate fields")
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
class ImportSignatureV1:
    formals: tuple[str, ...]
    sorts: tuple[Sort, ...]


@dataclass(frozen=True)
class ContextManagerContractRefV1:
    resolution_cid: str
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    catalog_cid: str
    member_cid: str
    payload_cid: str
    bridge_source_symbol: str
    import_signature: ImportSignatureV1
    semantics: ContextManagerSemanticsV1
    source_warrant_cids: tuple[str, ...]


@dataclass(frozen=True)
class ContextManagerResolutionGapV1:
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    target_symbol: str | None
    kind: str
    candidate_member_cids: tuple[str, ...]


ContextManagerResolutionV1 = ContextManagerContractRefV1 | ContextManagerResolutionGapV1


@dataclass(frozen=True)
class ResolvedContractRefsV1:
    catalog_cid: str
    table_cid: str
    by_use_site: Mapping[SourceFragmentCoordinateV1, ContextManagerResolutionV1]

    def require(self, use_site: SourceFragmentCoordinateV1) -> ContextManagerResolutionV1:
        try:
            return self.by_use_site[use_site]
        except KeyError as exc:
            raise ContractRefProtocolError(
                "BackendDefect: enrolled context-manager demand missing from resolution table"
            ) from exc


@dataclass(frozen=True)
class TreeConstructionContextV1:
    contract_refs: ResolvedContractRefsV1


_GAP_KINDS = frozenset({
    "runtime-selected", "unresolved-symbol", "ambiguous-symbol",
    "wrong-contract-kind", "signature-mismatch", "unauthenticated-member",
    "payload-cid-mismatch", "unsupported-cm-schema",
})


def _cid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise ContractRefProtocolError(f"{field} must be a CID")
    return value


def _decode_signature(raw: Any) -> ImportSignatureV1:
    if not isinstance(raw, dict) or set(raw) != {"formals", "sorts"}:
        raise ContractRefProtocolError("malformed import signature")
    if not isinstance(raw["formals"], list) or not all(isinstance(v, str) for v in raw["formals"]):
        raise ContractRefProtocolError("malformed import formals")
    try:
        from .context_manager_contract import _sort_from_json
        sorts = tuple(_sort_from_json(value) for value in raw["sorts"])
    except (KeyError, TypeError, ContextManagerContractError) as exc:
        raise ContractRefProtocolError("malformed import sorts") from exc
    if len(sorts) != len(raw["formals"]):
        raise ContractRefProtocolError("import signature arity mismatch")
    return ImportSignatureV1(tuple(raw["formals"]), sorts)


def _resolution_cid_preimage(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: raw[key] for key in (
        "schemaVersion", "demandCid", "useSite", "catalogCid", "memberCid",
        "payloadCid", "bridgeSourceSymbol", "importSignature", "semantics",
        "sourceWarrantCids",
    )}


def _hash_json(raw: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(raw)).encode("utf-8"))


def _decode_ref(raw: Any) -> ContextManagerContractRefV1:
    expected = {
        "kind", "schemaVersion", "resolutionCid", "demandCid", "useSite",
        "catalogCid", "memberCid", "payloadCid", "bridgeSourceSymbol",
        "importSignature", "semantics", "sourceWarrantCids",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ContractRefProtocolError("malformed context-manager contract ref")
    if raw["kind"] != "context-manager-contract-ref" or raw["schemaVersion"] != "1":
        raise ContractRefProtocolError("unsupported context-manager contract ref")
    resolution_cid = _cid(raw["resolutionCid"], "resolutionCid")
    if _hash_json(_resolution_cid_preimage(raw)) != resolution_cid:
        raise ContractRefProtocolError("resolution CID mismatch")
    try:
        semantics = _decode_semantics(raw["semantics"])
    except ContextManagerContractError as exc:
        raise ContractRefProtocolError("unsupported context-manager semantics") from exc
    warrants = raw["sourceWarrantCids"]
    if not isinstance(warrants, list):
        raise ContractRefProtocolError("sourceWarrantCids must be a list")
    return ContextManagerContractRefV1(
        resolution_cid, _cid(raw["demandCid"], "demandCid"),
        SourceFragmentCoordinateV1.decode(raw["useSite"]),
        _cid(raw["catalogCid"], "catalogCid"), _cid(raw["memberCid"], "memberCid"),
        _cid(raw["payloadCid"], "payloadCid"), raw["bridgeSourceSymbol"],
        _decode_signature(raw["importSignature"]), semantics,
        tuple(_cid(value, "sourceWarrantCid") for value in warrants),
    )


def decode_resolved_contract_refs(raw: Any) -> ResolvedContractRefsV1:
    if not isinstance(raw, dict) or set(raw) != {
        "kind", "schemaVersion", "catalogCid", "tableCid", "byUseSite"
    } or raw["kind"] != "resolved-contract-refs" or raw["schemaVersion"] != "1":
        raise ContractRefProtocolError("malformed resolved-contract-ref table")
    table_cid = _cid(raw["tableCid"], "tableCid")
    identity = {key: raw[key] for key in ("kind", "schemaVersion", "catalogCid", "byUseSite")}
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
        if resolution.get("kind") == "resolved" and set(resolution) == {"kind", "reference"}:
            value: ContextManagerResolutionV1 = _decode_ref(resolution["reference"])
            if value.use_site != use_site or value.catalog_cid != catalog_cid:
                raise ContractRefProtocolError("resolution coordinate/catalog mismatch")
        elif resolution.get("kind") == "unresolved" and set(resolution) == {"kind", "gap"}:
            gap = resolution["gap"]
            if not isinstance(gap, dict) or gap.get("kind") not in _GAP_KINDS:
                raise ContractRefProtocolError("malformed context-manager resolution gap")
            candidates = gap.get("candidateMemberCids")
            if not isinstance(candidates, list) or candidates != sorted(candidates):
                raise ContractRefProtocolError("candidate member CIDs must be sorted")
            value = ContextManagerResolutionGapV1(
                _cid(gap.get("demandCid"), "demandCid"),
                SourceFragmentCoordinateV1.decode(gap.get("useSite")),
                gap.get("targetSymbol"), gap["kind"],
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
