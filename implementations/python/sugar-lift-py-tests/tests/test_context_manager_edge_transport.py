import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    ImportSignatureV2,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ContextManagerResolutionGapV1,
    SourceFragmentCoordinateV1,
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc.context_manager_edge_dto import (
    ContextManagerEdgeDtoV1,
    ContextManagerEdgeTransportError,
)
from sugar_lift_py_tests.kit_rpc.lift_report_payload_dto import LiftReportPayloadDto


def _cid(char):
    return "blake3-512:" + char * 128


def _ref():
    site = SourceFragmentCoordinateV1(_cid("s"), 3, 9, 3, 18)
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=site,
        use_site_cid=_hash_json(site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=ImportSignatureV2(()),
        semantics=ProtocolResourceSemanticsV1(
            EnterResultContractV1(PrimitiveSort("Value")),
            ExitContractV1(NeverSuppressesDispositionV1()),
        ),
    )


def test_edge_from_derived_ref_is_content_addressed_and_separate():
    reference = _ref()
    edge = ContextManagerEdgeDtoV1.from_resolved(reference, reference.use_site)
    wire = edge.to_rpc()
    assert wire["schemaVersion"] == "derived-1"
    assert wire["targetContractCid"] == reference.contract_cid
    assert wire["provenanceCid"] == reference.provenance_cid
    assert wire["managerConstructionCid"] == reference.manager_construction_cid
    assert wire["semantics"]["exit"]["disposition"] == {"kind": "never-suppresses"}
    report = LiftReportPayloadDto(context_manager_edges=[edge]).to_rpc()
    assert report["contextManagerEdges"] == [wire]
    assert report["callEdges"] == []


def test_edge_constructor_rejects_coordinate_and_gap():
    reference = _ref()
    other = SourceFragmentCoordinateV1(_cid("s"), 4, 0, 4, 3)
    with pytest.raises(ContextManagerEdgeTransportError, match="use-site"):
        ContextManagerEdgeDtoV1.from_resolved(reference, other)
    gap = ContextManagerResolutionGapV1(
        _cid("d"), reference.use_site, None, "no-derived-contract", ()
    )
    with pytest.raises(ContextManagerEdgeTransportError, match="authenticated derived"):
        ContextManagerEdgeDtoV1.from_resolved(gap, gap.use_site)
