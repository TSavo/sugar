"""Authenticated function-contract coordinates installed before construction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import _decode_sort, _json_value
from .context_manager_resolution import SourceFragmentCoordinateV1
from .ir import (
    PrimitiveSort,
    Sort,
    Term,
    bool_const,
    ctor,
    make_var,
    num,
    real_lit,
    str_const,
)


class CallContractRefProtocolError(ValueError):
    pass


def _cid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise CallContractRefProtocolError(f"{field} must be a CID")
    return value


def _hash_json(raw: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(raw)).encode("utf-8"))


def _term(raw: Any) -> Term:
    if not isinstance(raw, dict):
        raise CallContractRefProtocolError("returnTerm must be a term object")
    kind = raw.get("kind")
    if kind == "var" and set(raw) == {"kind", "name"} and isinstance(raw["name"], str):
        return make_var(raw["name"])
    if kind == "const" and set(raw) == {"kind", "value", "sort"}:
        sort = raw["sort"]
        name = sort.get("name") if isinstance(sort, dict) else None
        value = raw["value"]
        if name == "String" and isinstance(value, str):
            return str_const(value)
        if name == "Bool" and isinstance(value, bool):
            return bool_const(value)
        if name == "Int" and isinstance(value, int) and not isinstance(value, bool):
            return num(value)
        if name == "Real" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return real_lit(str(value))
        raise CallContractRefProtocolError("unsupported returnTerm constant")
    if kind == "ctor" and set(raw) == {"kind", "name", "args"}:
        if not isinstance(raw["name"], str) or not isinstance(raw["args"], list):
            raise CallContractRefProtocolError("malformed returnTerm ctor")
        return ctor(raw["name"], [_term(arg) for arg in raw["args"]])
    raise CallContractRefProtocolError("unsupported returnTerm shape")


@dataclass(frozen=True)
class ResolvedCallContractRefV1:
    resolution_cid: str
    demand_cid: str
    use_site: SourceFragmentCoordinateV1 | None
    import_binding_cid: str
    catalog_cid: str
    member_cid: str
    contract_cid: str
    bridge_source_symbol: str
    formals: tuple[str, ...]
    sorts: tuple[Sort, ...]
    return_term: Term | None
    source_warrant_cids: tuple[str, ...]


class CallContractResolutionGapKindV1(str, Enum):
    TARGET_NOT_IN_CORPUS = "target-not-in-corpus"
    NO_AUTHENTICATED_CONTRACT = "no-authenticated-contract"
    AMBIGUOUS_TARGET = "ambiguous-target"
    IMPORT_SIGNATURE_MISMATCH = "import-signature-mismatch"
    WRONG_CONTRACT_KIND = "wrong-contract-kind"
    STALE_OR_MALFORMED_CONTRACT_REF = "stale-or-malformed-contract-ref"


@dataclass(frozen=True)
class CallContractResolutionGapV1:
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    import_binding_cid: str
    target_symbol: str | None
    kind: CallContractResolutionGapKindV1
    candidate_member_cids: tuple[str, ...]


CallContractResolutionV1 = ResolvedCallContractRefV1 | CallContractResolutionGapV1


@dataclass(frozen=True)
class ResolvedCallContractRefsV1:
    catalog_cid: str
    table_cid: str
    by_use_site: Mapping[SourceFragmentCoordinateV1, CallContractResolutionV1]

    def require(self, use_site: SourceFragmentCoordinateV1) -> CallContractResolutionV1:
        try:
            return self.by_use_site[use_site]
        except KeyError as exc:
            raise CallContractRefProtocolError(
                "BackendDefect: enrolled call demand missing from resolution table"
            ) from exc


def _decode_ref(raw: Any) -> ResolvedCallContractRefV1:
    expected = {
        "kind", "schemaVersion", "resolutionCid", "demandCid", "useSite",
        "importBindingCid", "catalogCid", "memberCid", "contractCid", "bridgeSourceSymbol",
        "importSignature", "returnTerm", "sourceWarrantCids",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise CallContractRefProtocolError("malformed resolved-call contract ref")
    if raw["kind"] != "resolved-call-contract-ref" or raw["schemaVersion"] != "1":
        raise CallContractRefProtocolError("unsupported resolved-call contract ref")
    signature = raw["importSignature"]
    if not isinstance(signature, dict) or set(signature) != {"formals", "sorts"}:
        raise CallContractRefProtocolError("malformed call import signature")
    if not isinstance(signature["formals"], list) or not all(
        isinstance(value, str) for value in signature["formals"]
    ):
        raise CallContractRefProtocolError("malformed call import formals")
    try:
        sorts = tuple(_decode_sort(value) for value in signature["sorts"])
    except Exception as exc:
        raise CallContractRefProtocolError("malformed call import sorts") from exc
    if len(sorts) != len(signature["formals"]):
        raise CallContractRefProtocolError("call import signature arity mismatch")
    warrants = raw["sourceWarrantCids"]
    if not isinstance(warrants, list):
        raise CallContractRefProtocolError("sourceWarrantCids must be a list")
    return_term = None if raw["returnTerm"] is None else _term(raw["returnTerm"])
    if return_term is not None:
        from .ir import _free_vars_in_term

        if not _free_vars_in_term(return_term) <= set(signature["formals"]):
            raise CallContractRefProtocolError(
                "returnTerm contains a variable not authenticated as a formal"
            )
    return ResolvedCallContractRefV1(
        _cid(raw["resolutionCid"], "resolutionCid"),
        _cid(raw["demandCid"], "demandCid"),
        SourceFragmentCoordinateV1.decode(raw["useSite"]),
        _cid(raw["importBindingCid"], "importBindingCid"),
        _cid(raw["catalogCid"], "catalogCid"),
        _cid(raw["memberCid"], "memberCid"),
        _cid(raw["contractCid"], "contractCid"),
        raw["bridgeSourceSymbol"],
        tuple(signature["formals"]), sorts, return_term,
        tuple(_cid(value, "sourceWarrantCid") for value in warrants),
    )


def decode_resolved_call_contract_refs(raw: Any) -> ResolvedCallContractRefsV1:
    if not isinstance(raw, dict) or set(raw) != {
        "kind", "schemaVersion", "catalogCid", "tableCid", "byUseSite"
    } or raw["kind"] != "resolved-call-contract-refs" or raw["schemaVersion"] != "1":
        raise CallContractRefProtocolError("malformed resolved-call contract-ref table")
    rows = raw["byUseSite"]
    if not isinstance(rows, list):
        raise CallContractRefProtocolError("byUseSite must be a list")
    decoded: dict[SourceFragmentCoordinateV1, CallContractResolutionV1] = {}
    catalog_cid = _cid(raw["catalogCid"], "catalogCid")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"useSite", "resolution"}:
            raise CallContractRefProtocolError("malformed call resolution row")
        use_site = SourceFragmentCoordinateV1.decode(row["useSite"])
        resolution = row["resolution"]
        if not isinstance(resolution, dict):
            raise CallContractRefProtocolError("malformed call resolution")
        if resolution.get("kind") == "resolved" and set(resolution) == {"kind", "reference"}:
            value: CallContractResolutionV1 = _decode_ref(resolution["reference"])
        elif resolution.get("kind") == "unresolved" and set(resolution) == {"kind", "gap"}:
            gap = resolution["gap"]
            candidates = gap.get("candidateMemberCids") if isinstance(gap, dict) else None
            if not isinstance(candidates, list) or candidates != sorted(candidates):
                raise CallContractRefProtocolError("candidate member CIDs must be sorted")
            value = CallContractResolutionGapV1(
                _cid(gap.get("demandCid"), "demandCid"), use_site,
                _cid(gap.get("importBindingCid"), "importBindingCid"),
                gap.get("targetSymbol"), CallContractResolutionGapKindV1(gap.get("kind")),
                tuple(_cid(cid, "candidateMemberCid") for cid in candidates),
            )
        else:
            raise CallContractRefProtocolError("unknown call resolution")
        decoded[use_site] = value
    identity = {key: raw[key] for key in ("kind", "schemaVersion", "catalogCid", "byUseSite")}
    if _hash_json(identity) != raw["tableCid"]:
        raise CallContractRefProtocolError("table CID mismatch")
    return ResolvedCallContractRefsV1(
        catalog_cid, _cid(raw["tableCid"], "tableCid"), MappingProxyType(decoded)
    )
