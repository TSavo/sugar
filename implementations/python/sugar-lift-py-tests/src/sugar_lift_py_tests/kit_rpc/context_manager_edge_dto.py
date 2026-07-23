"""Closed context-manager occurrence edge for the dedicated report lane."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sugar_lift_py_tests.context_manager_contract import (
    ImportSignatureV2,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    TotalCompletionV1,
    import_signature_to_value,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    SourceFragmentCoordinateV1,
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort, sort_to_value


class ContextManagerEdgeTransportError(ValueError):
    pass


def _json(value) -> Any:
    from sugar_lift_py_tests.canonicalizer import encode_jcs

    return json.loads(encode_jcs(value))


def _signature_wire(signature: ImportSignatureV2) -> dict[str, Any]:
    return _json(import_signature_to_value(signature))


def _admitted(reference: ContextManagerContractRefV1) -> bool:
    semantics = reference.semantics
    return (
        isinstance(semantics, ProtocolResourceSemanticsV1)
        and semantics.schema_version == "1"
        and isinstance(semantics.enter.completion, TotalCompletionV1)
        and semantics.enter.projection == "enter-result"
        and isinstance(semantics.enter.sort, PrimitiveSort)
        and semantics.enter.sort.name == "Value"
        and isinstance(semantics.exit.completion, TotalCompletionV1)
        and isinstance(semantics.exit.disposition, NeverSuppressesDispositionV1)
    )


@dataclass(frozen=True)
class ContextManagerEdgeDtoV1:
    edge_cid: str
    use_site: SourceFragmentCoordinateV1
    bridge_source_symbol: str
    import_signature: ImportSignatureV2
    target_contract_cid: str
    payload_cid: str
    demand_cid: str
    resolution_cid: str
    catalog_cid: str
    source_warrant_cids: tuple[str, ...]
    semantics: object
    kind: str = "context-manager-edge"
    schema_version: str = "1"

    @classmethod
    def from_resolved(cls, reference, use_site) -> "ContextManagerEdgeDtoV1":
        if not isinstance(reference, ContextManagerContractRefV1):
            raise ContextManagerEdgeTransportError(
                "context-manager edge requires a resolved authenticated ref"
            )
        if use_site != reference.use_site:
            raise ContextManagerEdgeTransportError(
                "context-manager edge use-site mismatch"
            )
        if not _admitted(reference):
            raise ContextManagerEdgeTransportError(
                "context-manager edge requires admitted typed NeverSuppresses semantics"
            )
        warrants = tuple(sorted(reference.source_warrant_cids))
        if len(warrants) != len(set(warrants)):
            raise ContextManagerEdgeTransportError(
                "context-manager edge warrant CIDs must be unique"
            )
        values = {
            "kind": "context-manager-edge",
            "schemaVersion": "1",
            "useSite": use_site.wire(),
            "managerIdentity": {
                "bridgeSourceSymbol": reference.bridge_source_symbol,
                "importSignature": _signature_wire(reference.import_signature),
            },
            "targetContractCid": reference.member_cid,
            "payloadCid": reference.payload_cid,
            "demandCid": reference.demand_cid,
            "resolutionCid": reference.resolution_cid,
            "catalogCid": reference.catalog_cid,
            "sourceWarrantCids": list(warrants),
            "semantics": _json(semantics_to_value(reference.semantics)),
        }
        return cls(
            edge_cid=_hash_json(values),
            use_site=use_site,
            bridge_source_symbol=reference.bridge_source_symbol,
            import_signature=reference.import_signature,
            target_contract_cid=reference.member_cid,
            payload_cid=reference.payload_cid,
            demand_cid=reference.demand_cid,
            resolution_cid=reference.resolution_cid,
            catalog_cid=reference.catalog_cid,
            source_warrant_cids=warrants,
            semantics=reference.semantics,
        )

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "edgeCid": self.edge_cid,
            "useSite": self.use_site.wire(),
            "managerIdentity": {
                "bridgeSourceSymbol": self.bridge_source_symbol,
                "importSignature": _signature_wire(self.import_signature),
            },
            "targetContractCid": self.target_contract_cid,
            "payloadCid": self.payload_cid,
            "demandCid": self.demand_cid,
            "resolutionCid": self.resolution_cid,
            "catalogCid": self.catalog_cid,
            "sourceWarrantCids": list(self.source_warrant_cids),
            "semantics": _json(semantics_to_value(self.semantics)),
        }
