"""Closed preconstruction routing authority for every enrolled ``with`` site."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .context_manager_contract import (
    EFFECT,
    EXCEPTION_INFO,
    WARNING_OBSERVATION,
    EffectMatcher,
    Expects,
    MessagePattern,
    Suppresses,
    semantics_to_value,
    _json_value,
)
from .context_manager_resolution import (
    ContextManagerContractRefV1,
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    _cid,
    _decode_ref,
    _hash_json,
)
from .canonicalizer import encode_jcs


class WithManagerAuthorityProtocolError(ValueError):
    pass


LegacyMembraneContractV1 = Expects | Suppresses


def _matcher_wire(matcher: EffectMatcher) -> dict[str, Any]:
    obligations = []
    for obligation in matcher.payload_obligations:
        if not isinstance(obligation, MessagePattern):
            raise WithManagerAuthorityProtocolError("unsupported legacy matcher obligation")
        obligations.append({"kind": "message-pattern", "pattern": obligation.pattern})
    return {
        "kind": matcher.kind,
        "name": matcher.name,
        "payloadObligations": obligations,
    }


def _contract_wire(contract: LegacyMembraneContractV1) -> dict[str, Any]:
    if isinstance(contract, Expects):
        if contract.binding not in (None, EXCEPTION_INFO, WARNING_OBSERVATION, EFFECT):
            raise WithManagerAuthorityProtocolError("unsupported legacy binding projection")
        return {
            "kind": "expects",
            "matcher": _matcher_wire(contract.matcher),
            "binding": contract.binding,
        }
    if isinstance(contract, Suppresses):
        return {"kind": "suppresses", "matcher": _matcher_wire(contract.matcher)}
    raise WithManagerAuthorityProtocolError("legacy token requires Expects or Suppresses")


def _decode_matcher(raw: Any) -> EffectMatcher:
    if not isinstance(raw, dict) or set(raw) != {"kind", "name", "payloadObligations"}:
        raise WithManagerAuthorityProtocolError("malformed legacy effect matcher")
    if raw["kind"] not in ("raise", "warning") or not isinstance(raw["name"], str):
        raise WithManagerAuthorityProtocolError("unsupported legacy effect matcher")
    obligations = raw["payloadObligations"]
    if not isinstance(obligations, list):
        raise WithManagerAuthorityProtocolError("malformed matcher obligations")
    decoded = []
    for obligation in obligations:
        if not isinstance(obligation, dict) or set(obligation) != {"kind", "pattern"} \
                or obligation["kind"] != "message-pattern" \
                or not isinstance(obligation["pattern"], str):
            raise WithManagerAuthorityProtocolError("malformed matcher obligation")
        decoded.append(MessagePattern(obligation["pattern"]))
    return EffectMatcher(raw["kind"], raw["name"], tuple(decoded))


def _decode_contract(raw: Any) -> LegacyMembraneContractV1:
    if not isinstance(raw, dict):
        raise WithManagerAuthorityProtocolError("malformed legacy membrane contract")
    if raw.get("kind") == "expects" and set(raw) == {"kind", "matcher", "binding"}:
        binding = raw["binding"]
        if binding not in (None, EXCEPTION_INFO, WARNING_OBSERVATION, EFFECT):
            raise WithManagerAuthorityProtocolError("unsupported legacy binding projection")
        return Expects(_decode_matcher(raw["matcher"]), binding)
    if raw.get("kind") == "suppresses" and set(raw) == {"kind", "matcher"}:
        return Suppresses(_decode_matcher(raw["matcher"]))
    raise WithManagerAuthorityProtocolError("unknown legacy membrane contract")


@dataclass(frozen=True)
class AuthenticatedLegacyMembraneRefV1:
    authentication_cid: str
    demand_cid: str
    use_site: SourceFragmentCoordinateV1
    manifest_cid: str
    enrollment_cid: str
    contract: LegacyMembraneContractV1

    @classmethod
    def mint_from_authenticated_identity(
        cls, *, demand_cid: str, use_site: SourceFragmentCoordinateV1,
        manifest_cid: str, enrollment_cid: str,
        contract: LegacyMembraneContractV1,
    ) -> "AuthenticatedLegacyMembraneRefV1":
        # This door consumes an authenticated identity CID. It never derives one.
        for value, field in ((demand_cid, "demandCid"),
                             (manifest_cid, "manifestCid"),
                             (enrollment_cid, "enrollmentCid")):
            _cid(value, field)
        preimage = {
            "schemaVersion": "1", "useSite": use_site.wire(),
            "demandCid": demand_cid,
            "manifestCid": manifest_cid, "enrollmentCid": enrollment_cid,
            "contract": _contract_wire(contract),
        }
        return cls(_hash_json(preimage), demand_cid, use_site, manifest_cid,
                   enrollment_cid, contract)

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": "authenticated-legacy-membrane-ref", "schemaVersion": "1",
            "authenticationCid": self.authentication_cid,
            "demandCid": self.demand_cid,
            "useSite": self.use_site.wire(),
            "manifestCid": self.manifest_cid,
            "enrollmentCid": self.enrollment_cid,
            "contract": _contract_wire(self.contract),
        }


def _decode_legacy_ref(raw: Any) -> AuthenticatedLegacyMembraneRefV1:
    expected = {"kind", "schemaVersion", "authenticationCid", "demandCid", "useSite",
                "manifestCid", "enrollmentCid", "contract"}
    if not isinstance(raw, dict) or set(raw) != expected \
            or raw["kind"] != "authenticated-legacy-membrane-ref" \
            or raw["schemaVersion"] != "1":
        raise WithManagerAuthorityProtocolError("malformed legacy membrane reference")
    token = AuthenticatedLegacyMembraneRefV1.mint_from_authenticated_identity(
        demand_cid=_cid(raw["demandCid"], "demandCid"),
        use_site=SourceFragmentCoordinateV1.decode(raw["useSite"]),
        manifest_cid=_cid(raw["manifestCid"], "manifestCid"),
        enrollment_cid=_cid(raw["enrollmentCid"], "enrollmentCid"),
        contract=_decode_contract(raw["contract"]),
    )
    if _cid(raw["authenticationCid"], "authenticationCid") != token.authentication_cid:
        raise WithManagerAuthorityProtocolError("legacy membrane authentication CID mismatch")
    return token


@dataclass(frozen=True)
class AuthenticatedLegacyMembrane:
    reference: AuthenticatedLegacyMembraneRefV1


@dataclass(frozen=True)
class ResolvedContextManager:
    reference: ContextManagerContractRefV1


@dataclass(frozen=True)
class UnresolvedContextManager:
    gap: ContextManagerResolutionGapV1


@dataclass(frozen=True)
class WithManagerAuthorityGapV1:
    use_site: SourceFragmentCoordinateV1
    kind: str


@dataclass(frozen=True)
class ConflictingAuthority:
    gap: WithManagerAuthorityGapV1


WithManagerAuthorityV1 = (
    AuthenticatedLegacyMembrane | ResolvedContextManager |
    UnresolvedContextManager | ConflictingAuthority
)


def _gap_wire(gap: ContextManagerResolutionGapV1) -> dict[str, Any]:
    return {
        "demandCid": gap.demand_cid, "useSite": gap.use_site.wire(),
        "targetSymbol": gap.target_symbol, "kind": gap.kind,
        "candidateMemberCids": list(gap.candidate_member_cids),
    }


def _ref_wire(reference: ContextManagerContractRefV1) -> dict[str, Any]:
    import json
    from .canonicalizer import encode_jcs
    from .ir import sort_to_value
    return {
        "kind": "context-manager-contract-ref", "schemaVersion": "1",
        "resolutionCid": reference.resolution_cid, "demandCid": reference.demand_cid,
        "useSite": reference.use_site.wire(), "catalogCid": reference.catalog_cid,
        "memberCid": reference.member_cid, "payloadCid": reference.payload_cid,
        "bridgeSourceSymbol": reference.bridge_source_symbol,
        "importSignature": {
            "formals": list(reference.import_signature.formals),
            "sorts": [json.loads(encode_jcs(sort_to_value(sort))) for sort in reference.import_signature.sorts],
        },
        "semantics": json.loads(encode_jcs(semantics_to_value(reference.semantics))),
        "sourceWarrantCids": list(reference.source_warrant_cids),
    }


def _authority_wire(authority: WithManagerAuthorityV1) -> dict[str, Any]:
    if isinstance(authority, AuthenticatedLegacyMembrane):
        return {"kind": "authenticated-legacy-membrane", "reference": authority.reference.to_wire()}
    if isinstance(authority, ResolvedContextManager):
        return {"kind": "resolved-context-manager", "reference": _ref_wire(authority.reference)}
    if isinstance(authority, UnresolvedContextManager):
        return {"kind": "unresolved-context-manager", "gap": _gap_wire(authority.gap)}
    return {"kind": "conflicting-authority", "gap": {
        "kind": authority.gap.kind, "useSite": authority.gap.use_site.wire(),
    }}


@dataclass(frozen=True)
class WithManagerAuthoritiesV1:
    table_cid: str
    by_use_site: Mapping[SourceFragmentCoordinateV1, WithManagerAuthorityV1]

    @classmethod
    def assemble(cls, refs: ResolvedContractRefsV1,
                 legacy_tokens: Sequence[AuthenticatedLegacyMembraneRefV1]):
        tokens: dict[SourceFragmentCoordinateV1, list[AuthenticatedLegacyMembraneRefV1]] = {}
        for token in legacy_tokens:
            tokens.setdefault(token.use_site, []).append(token)
        unknown = set(tokens).difference(refs.by_use_site)
        if unknown:
            raise WithManagerAuthorityProtocolError("legacy token use-site has no enrolled demand")
        rows: dict[SourceFragmentCoordinateV1, WithManagerAuthorityV1] = {}
        for site, resolution in refs.by_use_site.items():
            candidates = tokens.get(site, [])
            if len(candidates) > 1:
                rows[site] = ConflictingAuthority(
                    WithManagerAuthorityGapV1(site, "duplicate-legacy-membrane-token"))
            elif candidates and candidates[0].demand_cid != resolution.demand_cid:
                rows[site] = ConflictingAuthority(
                    WithManagerAuthorityGapV1(site, "mismatched-legacy-demand"))
            elif isinstance(resolution, ContextManagerContractRefV1) and candidates:
                rows[site] = ConflictingAuthority(
                    WithManagerAuthorityGapV1(site, "conflicting-manager-authority"))
            elif candidates:
                rows[site] = AuthenticatedLegacyMembrane(candidates[0])
            elif isinstance(resolution, ContextManagerContractRefV1):
                rows[site] = ResolvedContextManager(resolution)
            else:
                rows[site] = UnresolvedContextManager(resolution)
        temporary = cls("", MappingProxyType(rows))
        return cls(_hash_json(temporary._identity()), MappingProxyType(rows))

    def _identity(self) -> dict[str, Any]:
        return {"kind": "with-manager-authorities", "schemaVersion": "1",
                "byUseSite": [{"useSite": site.wire(), "authority": _authority_wire(authority)}
                              for site, authority in sorted(self.by_use_site.items())]}

    def to_wire(self) -> dict[str, Any]:
        return {**self._identity(), "tableCid": self.table_cid}

    def require(self, site: SourceFragmentCoordinateV1) -> WithManagerAuthorityV1:
        try:
            return self.by_use_site[site]
        except KeyError as exc:
            raise WithManagerAuthorityProtocolError(
                "BackendDefect: enrolled With missing from authority table") from exc


def decode_with_manager_authorities(raw: Any) -> WithManagerAuthoritiesV1:
    if not isinstance(raw, dict) or set(raw) != {"kind", "schemaVersion", "tableCid", "byUseSite"} \
            or raw["kind"] != "with-manager-authorities" or raw["schemaVersion"] != "1" \
            or not isinstance(raw["byUseSite"], list):
        raise WithManagerAuthorityProtocolError("malformed With authority table")
    identity = {key: raw[key] for key in ("kind", "schemaVersion", "byUseSite")}
    if _hash_json(identity) != _cid(raw["tableCid"], "tableCid"):
        raise WithManagerAuthorityProtocolError("With authority table CID mismatch")
    decoded = {}
    for row in raw["byUseSite"]:
        if not isinstance(row, dict) or set(row) != {"useSite", "authority"}:
            raise WithManagerAuthorityProtocolError("malformed With authority row")
        site = SourceFragmentCoordinateV1.decode(row["useSite"])
        authority = row["authority"]
        if not isinstance(authority, dict):
            raise WithManagerAuthorityProtocolError("malformed With authority")
        if authority.get("kind") == "authenticated-legacy-membrane" and set(authority) == {"kind", "reference"}:
            value: WithManagerAuthorityV1 = AuthenticatedLegacyMembrane(_decode_legacy_ref(authority["reference"]))
        elif authority.get("kind") == "resolved-context-manager" and set(authority) == {"kind", "reference"}:
            value = ResolvedContextManager(_decode_ref(authority["reference"]))
        elif authority.get("kind") == "unresolved-context-manager" and set(authority) == {"kind", "gap"}:
            gap = authority["gap"]
            if not isinstance(gap, dict) or set(gap) != {"demandCid", "useSite", "targetSymbol", "kind", "candidateMemberCids"}:
                raise WithManagerAuthorityProtocolError("malformed unresolved With authority")
            value = UnresolvedContextManager(ContextManagerResolutionGapV1(
                _cid(gap["demandCid"], "demandCid"),
                SourceFragmentCoordinateV1.decode(gap["useSite"]), gap["targetSymbol"],
                gap["kind"], tuple(_cid(cid, "candidateMemberCid") for cid in gap["candidateMemberCids"]),
            ))
        elif authority.get("kind") == "conflicting-authority" and set(authority) == {"kind", "gap"}:
            gap = authority["gap"]
            value = ConflictingAuthority(WithManagerAuthorityGapV1(
                SourceFragmentCoordinateV1.decode(gap["useSite"]), gap["kind"]))
        else:
            raise WithManagerAuthorityProtocolError("unknown With authority variant")
        coordinate = value.reference.use_site if isinstance(value, (AuthenticatedLegacyMembrane, ResolvedContextManager)) else value.gap.use_site
        if coordinate != site or site in decoded:
            raise WithManagerAuthorityProtocolError("duplicate or mismatched With authority coordinate")
        decoded[site] = value
    return WithManagerAuthoritiesV1(raw["tableCid"], MappingProxyType(decoded))
