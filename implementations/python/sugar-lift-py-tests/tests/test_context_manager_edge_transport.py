from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ProtocolResourceSemanticsV1,
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ContextManagerResolutionGapV1,
    ImportSignatureV2,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc.context_manager_edge_dto import (
    ContextManagerEdgeDtoV1,
    ContextManagerEdgeTransportError,
)
from sugar_lift_py_tests.kit_rpc.lift_report_payload_dto import LiftReportPayloadDto


def _cid(char):
    return "blake3-512:" + char * 128


def _ref(warrants=None):
    site = SourceFragmentCoordinateV1(_cid("s"), 3, 9, 3, 18)
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=site,
        catalog_cid=_cid("c"),
        member_cid=_cid("m"),
        payload_cid=_cid("p"),
        bridge_source_symbol="context-manager:dependency.manager",
        import_signature=ImportSignatureV2(()),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(PrimitiveSort("Value")),
            exit=ExitContractV1(NeverSuppressesDispositionV1()),
        ),
        source_warrant_cids=tuple(warrants or (_cid("a"), _cid("b"))),
    )


def test_edge_from_resolved_is_content_addressed_and_report_lane_is_separate():
    reference = _ref()
    edge = ContextManagerEdgeDtoV1.from_resolved(reference, reference.use_site)
    wire = edge.to_rpc()
    assert wire["kind"] == "context-manager-edge"
    assert wire["schemaVersion"] == "1"
    assert wire["targetContractCid"] == reference.member_cid
    assert wire["payloadCid"] == reference.payload_cid
    assert wire["demandCid"] == reference.demand_cid
    assert wire["resolutionCid"] == reference.resolution_cid
    assert wire["catalogCid"] == reference.catalog_cid
    assert wire["sourceWarrantCids"] == sorted(reference.source_warrant_cids)
    assert wire["semantics"]["exit"]["disposition"] == {"kind": "never-suppresses"}

    report = LiftReportPayloadDto(context_manager_edges=[edge]).to_rpc()
    assert report["contextManagerEdges"] == [wire]
    assert report["callEdges"] == []


def test_edge_constructor_rejects_coordinate_gap_and_duplicate_warrants():
    reference = _ref()
    other_site = SourceFragmentCoordinateV1(_cid("s"), 4, 0, 4, 3)
    with pytest.raises(ContextManagerEdgeTransportError, match="use-site"):
        ContextManagerEdgeDtoV1.from_resolved(reference, other_site)

    gap = ContextManagerResolutionGapV1(
        demand_cid=_cid("d"),
        use_site=reference.use_site,
        target_symbol="context-manager:dependency.manager",
        kind="unresolved-symbol",
        candidate_member_cids=(),
    )
    with pytest.raises(ContextManagerEdgeTransportError, match="resolved"):
        ContextManagerEdgeDtoV1.from_resolved(gap, gap.use_site)

    duplicate = _ref((_cid("a"), _cid("a")))
    with pytest.raises(ContextManagerEdgeTransportError, match="unique"):
        ContextManagerEdgeDtoV1.from_resolved(duplicate, duplicate.use_site)
