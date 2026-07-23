from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.call_contract_resolution import (
    CallContractRefProtocolError,
    ResolvedCallContractRefV1,
    ResolvedCallContractRefsV1,
    decode_resolved_call_contract_refs,
)
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests import lift_rpc
from sugar_source_tree.panic import SugarNotWritten


CID = "blake3-512:" + "1" * 128
MEMBER_CID = "blake3-512:" + "2" * 128
CATALOG_CID = "blake3-512:" + "3" * 128
DEMAND_CID = "blake3-512:" + "4" * 128
RESOLUTION_CID = "blake3-512:" + "5" * 128
TABLE_CID = "blake3-512:" + "6" * 128


def _reference() -> ResolvedCallContractRefV1:
    return ResolvedCallContractRefV1(
        resolution_cid=RESOLUTION_CID,
        demand_cid=DEMAND_CID,
        use_site=None,
        import_binding_cid=CATALOG_CID,
        catalog_cid=CATALOG_CID,
        member_cid=MEMBER_CID,
        contract_cid=CID,
        bridge_source_symbol="python:pandas.fixture.pair",
        formals=("x",),
        sorts=(PrimitiveSort("Value"),),
        return_term=ctor("python:tuple", [make_var("x"), make_var("x")]),
        source_warrant_cids=(),
    )


def test_authenticated_structural_return_projects_from_one_bridged_contract():
    sugar = CallSiteSugar(
        target_name="pair",
        args=(NameSugar("value", site="value"),),
        site="consumer.py:2",
        contract_ref=_reference(),
    )

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert outcome.value.to_term(owner="test") == ctor(
        "python:tuple", [make_var("value"), make_var("value")]
    )
    assert outcome.value.contract_cid == CID
    assert outcome.value.member_cid == MEMBER_CID
    assert outcome.value.callsites()[0].target_contract_cid == CID
    assert outcome.value.callsites()[0].authenticated_target_symbol == (
        "python:pandas.fixture.pair"
    )


def test_unresolved_or_non_structural_reference_stays_loud():
    unresolved = CallSiteSugar(
        target_name="missing",
        args=(),
        site="consumer.py:2",
        contract_ref=None,
        contract_resolution_gap="unresolved-symbol",
    )
    with pytest.raises(SugarNotWritten, match="unresolved-symbol"):
        unresolved.desugar(None)

    non_structural = _reference().__class__(
        **{**_reference().__dict__, "return_term": ctor("call:other", [str_const("x")])}
    )
    with pytest.raises(SugarNotWritten, match="structural return"):
        CallSiteSugar(
            target_name="pair",
            args=(NameSugar("value", site="value"),),
            site="consumer.py:2",
            contract_ref=non_structural,
        ).desugar(None)


def test_fabricated_or_unauthenticated_reference_fails_decode():
    wire = {
        "kind": "resolved-call-contract-refs",
        "schemaVersion": "1",
        "catalogCid": CATALOG_CID,
        "tableCid": TABLE_CID,
        "byUseSite": [
            {
                "useSite": {
                    "sourceCid": CID,
                    "startLine": 2,
                    "startCol": 4,
                    "endLine": 2,
                    "endCol": 11,
                },
                "resolution": {
                    "kind": "resolved",
                    "reference": {
                        "kind": "resolved-call-contract-ref",
                        "schemaVersion": "1",
                        "resolutionCid": RESOLUTION_CID,
                        "demandCid": DEMAND_CID,
                        "useSite": {
                            "sourceCid": CID,
                            "startLine": 2,
                            "startCol": 4,
                            "endLine": 2,
                            "endCol": 11,
                        },
                        "importBindingCid": CATALOG_CID,
                        "catalogCid": CATALOG_CID,
                        "memberCid": "fabricated:member",
                        "contractCid": CID,
                        "bridgeSourceSymbol": "python:pandas.fixture.pair",
                        "importSignature": {
                            "formals": ["x"],
                            "sorts": [{"kind": "primitive", "name": "Value"}],
                        },
                        "returnTerm": {
                            "kind": "ctor",
                            "name": "python:tuple",
                            "args": [{"kind": "var", "name": "x"}],
                        },
                        "sourceWarrantCids": [],
                    },
                },
            }
        ],
    }
    with pytest.raises(CallContractRefProtocolError, match="memberCid must be a CID"):
        decode_resolved_call_contract_refs(wire)


def test_return_projection_with_unauthenticated_free_name_stays_loud():
    reference = _reference().__class__(
        **{
            **_reference().__dict__,
            "return_term": ctor("python:tuple", [make_var("not_a_formal")]),
        }
    )
    with pytest.raises(SugarNotWritten, match="unbound projection"):
        CallSiteSugar(
            target_name="pair",
            args=(NameSugar("value", site="value"),),
            site="consumer.py:2",
            contract_ref=reference,
        ).desugar(None)


def test_import_demand_enrollment_has_positional_arity_and_module_identity(tmp_path):
    (tmp_path / "producer.py").write_text("def pair(x):\n    return (x, x)\n")
    (tmp_path / "consumer.py").write_text(
        "from producer import pair\n"
        "value = pair(1)\n"
        "not_enrolled = pair(x=1)\n"
    )

    rows = lift_rpc._call_contract_demand_rows(tmp_path)

    assert len(rows) == 1
    assert rows[0]["targetSymbol"] == "python:producer.pair"
    assert rows[0]["importBindingCid"].startswith("blake3-512:")
    assert rows[0]["importSignature"] == {
        "formals": [],
        "sorts": [{"kind": "primitive", "name": "Value"}],
    }


def test_import_binding_authenticates_alias_and_module_identity(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from first import pair as renamed\n"
        "from second import pair as other\n"
        "a = renamed()\n"
        "b = other()\n"
        "def pair():\n    return (0, 0)\n"
        "c = pair()\n"
    )

    rows = lift_rpc._call_contract_demand_rows(tmp_path)

    assert [row["targetSymbol"] for row in rows] == [
        "python:first.pair", "python:second.pair"
    ]
    assert rows[0]["importBindingCid"] != rows[1]["importBindingCid"]


def test_parser_backed_imported_call_consumes_prebound_contract_ref(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        ResolvedContractRefsV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    consumer = tmp_path / "consumer.py"
    consumer.write_text("from producer import pair\nvalue = pair(v)\n")
    row = lift_rpc._call_contract_demand_rows(tmp_path)[0]
    coordinate = SourceFragmentCoordinateV1.decode(row["useSite"])
    reference = replace(
        _reference(),
        use_site=coordinate,
        import_binding_cid=row["importBindingCid"],
    )
    table = ResolvedCallContractRefsV1(
        CATALOG_CID,
        TABLE_CID,
        MappingProxyType({coordinate: reference}),
    )
    cm_refs = ResolvedContractRefsV1(CATALOG_CID, TABLE_CID, MappingProxyType({}))
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=TreeConstructionContextV1(
            cm_refs, call_contract_refs=table, workspace_root=str(tmp_path)
        ),
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))

    outcome = call.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert outcome.value.contract_cid == CID
    assert outcome.value.callsites()[0].target_contract_cid == CID


def test_producer_contract_exports_the_same_module_qualified_symbol(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        ResolvedContractRefsV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows
    from sugar_source_tree.tree import SourceFile

    producer = tmp_path / "producer.py"
    producer.write_text("def pair():\n    return (1, 2)\n")
    tree = SourceFile(
        path_source(str(producer)),
        construction_context=TreeConstructionContextV1(
            ResolvedContractRefsV1(CATALOG_CID, TABLE_CID, MappingProxyType({})),
            workspace_root=str(tmp_path),
        ),
    )
    function = next(tree.functions())

    _, rows = function_contract_rows(function, "producer.py")

    assert rows is not None
    assert rows[0].bridge_source_symbol == "python:producer.pair"
