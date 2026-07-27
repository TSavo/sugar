from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.context_manager_resolution import (
    ContractRefProtocolError,
    OpaqueSourceCallObligationV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
    decode_resolved_contract_refs,
)


def test_opaque_source_call_obligation_transport_is_frozen_and_inspectable():
    coordinate = SourceFragmentCoordinateV1(
        "blake3-512:" + "a" * 128,
        7,
        8,
        7,
        19,
    )
    owner_cid = "blake3-512:" + "b" * 128
    obligation = OpaqueSourceCallObligationV1(coordinate, "func", owner_cid)
    table = {coordinate: obligation}
    context = TreeConstructionContextV1.for_source_call_construction(
        opaque_source_call_obligations=table
    )

    assert context.opaque_source_call_obligations is table
    assert context.opaque_source_call_obligations[coordinate] == obligation
    assert obligation.coordinate == coordinate
    assert obligation.target_name == "func"
    assert obligation.resolved_object_cid == owner_cid
    with pytest.raises(FrozenInstanceError):
        obligation.target_name = "other"

    empty = TreeConstructionContextV1.for_source_call_construction()
    assert empty.opaque_source_call_obligations == {}


def unresolved_table():
    cid = "blake3-512:" + "1" * 128
    demand_cid = "blake3-512:" + "2" * 128
    use_site = {
        "sourceCid": cid,
        "startLine": 3,
        "startCol": 4,
        "endLine": 3,
        "endCol": 12,
    }
    identity = {
        "kind": "resolved-contract-refs",
        "schemaVersion": "1",
        "catalogCid": cid,
        "byUseSite": [
            {
                "useSite": use_site,
                "resolution": {
                    "kind": "unresolved",
                    "gap": {
                        "demandCid": demand_cid,
                        "useSite": use_site,
                        "targetSymbol": "context-manager:fixture.missing",
                        "kind": "unresolved-symbol",
                        "candidateMemberCids": [],
                    },
                },
            }
        ],
    }
    return {**identity, "tableCid": _hash_json(identity)}


def test_table_is_frozen_and_missing_enrolled_coordinate_is_backend_defect():
    table = decode_resolved_contract_refs(unresolved_table())
    with pytest.raises(TypeError):
        table.by_use_site[next(iter(table.by_use_site))] = object()
    missing = SourceFragmentCoordinateV1("blake3-512:" + "3" * 128, 1, 0, 1, 1)
    with pytest.raises(ContractRefProtocolError, match="BackendDefect"):
        table.require(missing)


def test_bind_rpc_freezes_one_generation_and_acknowledges_exact_table_cid(monkeypatch):
    sent = []
    monkeypatch.setattr(lift_rpc, "_BOUND_CONTRACT_REFS", None)
    monkeypatch.setattr(lift_rpc, "_send", sent.append)
    wire = unresolved_table()
    assert lift_rpc._dispatch_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": lift_rpc.BIND_CONTRACT_REFS_RPC_METHOD,
            "params": {"contractRefs": wire},
        }
    )
    assert sent[0]["result"]["tableCid"] == wire["tableCid"]
    assert set(sent[0]["result"]) == {"tableCid"}
    assert isinstance(lift_rpc._BOUND_CONTRACT_REFS.by_use_site, MappingProxyType)

    other = unresolved_table()
    other["catalogCid"] = "blake3-512:" + "4" * 128
    identity = {
        key: other[key] for key in ("kind", "schemaVersion", "catalogCid", "byUseSite")
    }
    other["tableCid"] = _hash_json(identity)
    with pytest.raises(ValueError, match="already frozen"):
        lift_rpc._dispatch_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": lift_rpc.BIND_CONTRACT_REFS_RPC_METHOD,
                "params": {"contractRefs": other},
            }
        )


def test_malformed_table_cid_and_unsorted_ambiguity_are_loud():
    stale = unresolved_table()
    stale["tableCid"] = "blake3-512:" + "f" * 128
    with pytest.raises(ContractRefProtocolError, match="table CID mismatch"):
        decode_resolved_contract_refs(stale)

    ambiguous = unresolved_table()
    gap = ambiguous["byUseSite"][0]["resolution"]["gap"]
    gap["kind"] = "ambiguous-symbol"
    gap["candidateMemberCids"] = [
        "blake3-512:" + "b" * 128,
        "blake3-512:" + "a" * 128,
    ]
    identity = {
        key: ambiguous[key]
        for key in ("kind", "schemaVersion", "catalogCid", "byUseSite")
    }
    ambiguous["tableCid"] = _hash_json(identity)
    with pytest.raises(ContractRefProtocolError, match="must be sorted"):
        decode_resolved_contract_refs(ambiguous)


def test_demand_enrollment_uses_typed_with_coordinate_without_spelling_authority(
    tmp_path, monkeypatch
):
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from dependency_that_is_not_present import manager as renamed\n"
        "def f():\n"
        "    with renamed():\n"
        "        pass\n"
    )
    from sugar_source_tree.nodes import With

    monkeypatch.setattr(
        With,
        "sugar",
        lambda self: (_ for _ in ()).throw(
            AssertionError("demand pass constructed Sugar")
        ),
    )
    rows = lift_rpc._context_manager_demand_rows(tmp_path)
    assert len(rows) == 1
    # This structural pass never infers authority from the alias spelling.
    # _preconstruction_demand_rows joins the separately authenticated lexical
    # ImportBinding at this exact coordinate.
    assert rows[0]["targetSymbol"] is None
    assert rows[0]["gapKind"] == "runtime-selected"
    assert rows[0]["useSite"]["sourceCid"].startswith("blake3-512:")


def test_kit_has_no_context_manager_admission_declaration_door(monkeypatch):
    sent = []
    monkeypatch.setattr(lift_rpc, "_BOUND_CONTRACT_REFS", None)
    monkeypatch.setattr(lift_rpc, "_ENUMERATION_ACTIVE", False)
    monkeypatch.setattr(lift_rpc, "_send", sent.append)
    lift_rpc._handle_enumerate(
        9,
        {
            "level": "contract-declarations",
            "workspace_root": ".",
        },
    )
    assert sent[-1] == {"jsonrpc": "2.0", "id": 9, "result": {"rows": []}}
