"""Closed edge from a With occurrence to a construction-derived CM summary."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
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
from sugar_lift_py_tests.ir import PrimitiveSort


class ContextManagerEdgeTransportError(ValueError):
    pass


def _json(value) -> Any:
    from sugar_lift_py_tests.canonicalizer import encode_jcs

    return json.loads(encode_jcs(value))


def _admitted(reference: ContextManagerContractRefV1) -> bool:
    semantics = reference.semantics
    return isinstance(semantics, EffectBoundarySemanticsV1) or (
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
    reference: ContextManagerContractRefV1
    kind: str = "context-manager-edge"
    schema_version: str = "derived-1"

    @classmethod
    def from_resolved(cls, reference, use_site) -> "ContextManagerEdgeDtoV1":
        if not isinstance(reference, ContextManagerContractRefV1):
            raise ContextManagerEdgeTransportError(
                "context-manager edge requires an authenticated derived ref"
            )
        if use_site != reference.use_site:
            raise ContextManagerEdgeTransportError(
                "context-manager edge use-site mismatch"
            )
        if not _admitted(reference):
            raise ContextManagerEdgeTransportError(
                "context-manager edge requires admitted closed semantics"
            )
        values = cls._values(reference)
        return cls(_hash_json(values), reference)

    @staticmethod
    def _values(reference: ContextManagerContractRefV1) -> dict[str, Any]:
        return {
            "kind": "context-manager-edge",
            "schemaVersion": "derived-1",
            "useSite": reference.use_site.wire(),
            "useSiteCid": reference.use_site_cid,
            "authenticatedImportUseCid": reference.authenticated_import_use_cid,
            "importBindingCid": reference.import_binding_cid,
            "constructionContextGenerationCid": reference.construction_context_generation_cid,
            "targetContractCid": reference.contract_cid,
            "payloadCid": reference.payload_cid,
            "provenanceCid": reference.provenance_cid,
            "distributionArtifactCid": reference.distribution_artifact_cid,
            "dependencyArtifactGraphCid": reference.dependency_artifact_graph_cid,
            "moduleSourceCid": reference.module_source_cid,
            "resolvedDefinitionCid": reference.resolved_definition_cid,
            "managerConstructionCid": reference.manager_construction_cid,
            "enterTestimonyCid": reference.enter_testimony_cid,
            "exitTestimonyCid": reference.exit_testimony_cid,
            "demandCid": reference.demand_cid,
            "resolutionCid": reference.resolution_cid,
            "importSignature": _json(
                import_signature_to_value(reference.import_signature)
            ),
            "semantics": _json(semantics_to_value(reference.semantics)),
        }

    def to_rpc(self) -> dict[str, Any]:
        values = self._values(self.reference)
        return {**values, "edgeCid": self.edge_cid}
