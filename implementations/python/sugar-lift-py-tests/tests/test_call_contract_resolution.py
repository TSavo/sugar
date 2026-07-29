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
from sugar_source_tree.panic import BackendDefect, SugarNotWritten

CID = "blake3-512:" + "1" * 128
MEMBER_CID = "blake3-512:" + "2" * 128
CATALOG_CID = "blake3-512:" + "3" * 128
DEMAND_CID = "blake3-512:" + "4" * 128
RESOLUTION_CID = "blake3-512:" + "5" * 128
TABLE_CID = "blake3-512:" + "6" * 128


def _site(line: int = 2) -> dict:
    return {
        "sourceCid": CID,
        "startLine": line,
        "startCol": 4,
        "endLine": line,
        "endCol": 11,
    }


def _gap_row(line: int = 2) -> dict:
    return {
        "useSite": _site(line),
        "resolution": {
            "kind": "unresolved",
            "gap": {
                "demandCid": DEMAND_CID,
                "useSite": _site(line),
                "importBindingCid": CATALOG_CID,
                "targetSymbol": "python:producer.pair",
                "kind": "no-authenticated-contract",
                "candidateMemberCids": [],
            },
        },
    }


def _table(rows: list[dict], enrolled: list[dict] | None = None) -> dict:
    from sugar_lift_py_tests.call_contract_resolution import _hash_json

    value = {
        "kind": "resolved-call-contract-refs",
        "schemaVersion": "1",
        "catalogCid": CATALOG_CID,
        "enrolledUseSites": (
            enrolled if enrolled is not None else [row["useSite"] for row in rows]
        ),
        "byUseSite": rows,
    }
    return {**value, "tableCid": _hash_json(value)}


def test_decoder_rejects_duplicate_rows_and_row_identity_mismatches():
    row = _gap_row()
    with pytest.raises(CallContractRefProtocolError, match="duplicate use-site"):
        decode_resolved_call_contract_refs(_table([row, row], enrolled=[_site()]))

    mismatched_gap = _gap_row()
    mismatched_gap["resolution"]["gap"]["useSite"] = _site(3)
    with pytest.raises(CallContractRefProtocolError, match="row use-site"):
        decode_resolved_call_contract_refs(_table([mismatched_gap]))


def test_decoder_rejects_missing_enrolled_row():
    with pytest.raises(
        CallContractRefProtocolError, match="enrolled call demand missing"
    ):
        decode_resolved_call_contract_refs(_table([], enrolled=[_site()]))


def test_call_distinguishes_non_enrolled_local_call_from_missing_enrolled_row(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        ResolvedContractRefsV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "consumer.py"
    path.write_text("local(value)\nimported(value)\n")
    source = path_source(str(path))
    source_cid = source[2]
    local_site = SourceFragmentCoordinateV1(source_cid, 1, 0, 1, 12)
    imported_site = SourceFragmentCoordinateV1(source_cid, 2, 0, 2, 15)
    call_refs = ResolvedCallContractRefsV1(
        CATALOG_CID,
        TABLE_CID,
        MappingProxyType({}),
        frozenset({imported_site}),
    )
    cm_refs = ResolvedContractRefsV1(CATALOG_CID, TABLE_CID, MappingProxyType({}))
    tree = SourceFile(
        source,
        construction_context=TreeConstructionContextV1(
            cm_refs, call_contract_refs=call_refs
        ),
    )
    calls = list(node for node in tree.nodes() if isinstance(node, Call))

    assert local_site not in call_refs.enrolled_use_sites
    assert calls[0].sugar().contract_ref is None
    with pytest.raises(BackendDefect, match="enrolled call demand missing"):
        calls[1].sugar()


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
        contract_decl=MappingProxyType({"kind": "contract"}),
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
        "enrolledUseSites": [_site()],
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
                        "contractDecl": {"kind": "contract"},
                    },
                },
            }
        ],
    }
    with pytest.raises(CallContractRefProtocolError, match="memberCid must be a CID"):
        decode_resolved_call_contract_refs(wire)


def test_python_intake_rejects_stale_semantic_contract_cid():
    from sugar_lift_py_tests.call_contract_resolution import _decode_ref

    raw = {
        "kind": "resolved-call-contract-ref",
        "schemaVersion": "1",
        "resolutionCid": RESOLUTION_CID,
        "demandCid": DEMAND_CID,
        "useSite": {
            "sourceCid": CID,
            "startLine": 2,
            "startCol": 0,
            "endLine": 2,
            "endCol": 7,
        },
        "importBindingCid": CATALOG_CID,
        "catalogCid": CATALOG_CID,
        "memberCid": MEMBER_CID,
        "contractCid": CID,
        "bridgeSourceSymbol": "python:producer.pair",
        "importSignature": {"formals": [], "sorts": []},
        "returnTerm": None,
        "sourceWarrantCids": [],
        "contractDecl": {"kind": "contract", "name": "changed"},
    }
    with pytest.raises(
        CallContractRefProtocolError, match="stale semantic contract CID"
    ):
        _decode_ref(raw)


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
        "from producer import pair\n" "value = pair(1)\n" "not_enrolled = pair(x=1)\n"
    )

    rows = [
        row
        for row in lift_rpc._call_contract_demand_rows(tmp_path)
        if row["kind"] == "call-contract-demand"
    ]

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

    rows = [
        row
        for row in lift_rpc._call_contract_demand_rows(tmp_path)
        if row["kind"] == "call-contract-demand"
    ]

    assert [row["targetSymbol"] for row in rows] == [
        "python:first.pair",
        "python:second.pair",
    ]
    assert rows[0]["importBindingCid"] != rows[1]["importBindingCid"]


def test_imported_attribute_chain_call_keeps_exact_use_site_and_shadowing(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "import os\n"
        "truth = os.path.dirname('value')\n"
        "def shadowed(os):\n"
        "    return os.path.dirname('value')\n"
    )
    source, _filename, source_cid = path_source(str(consumer))
    rows, outcomes = authenticated_import_uses(
        tmp_path, consumer, source, source_cid
    )

    assert len(rows) == 1
    assert rows[0]["targetSymbol"] == "python:os.path.dirname"
    assert rows[0]["kind"] == "call-contract-demand"
    assert rows[0]["authenticatedImportUse"]["useSite"] == rows[0]["useSite"]
    assert rows[0]["authenticatedImportUse"]["importBindingCid"] == rows[0][
        "importBindingCid"
    ]
    assert "shadowed-non-import" in outcomes.values()


def test_import_binding_is_lexical_and_shadowing_never_inherits_import(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair as renamed\n"
        "direct = renamed(0)\n"
        "def parameter(renamed):\n    return renamed(1)\n"
        "def assigned():\n    renamed(2)\n    renamed = local\n"
        "def nested():\n    def renamed(x): return x\n    return renamed(3)\n"
        "def branch(flag):\n"
        "    if flag:\n        from producer import pair as maybe\n"
        "    else:\n        maybe = local\n"
        "    return maybe(4)\n"
    )
    source, _filename, source_cid = path_source(str(consumer))
    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert [row["targetSymbol"] for row in rows] == ["python:producer.pair"]
    assert "shadowed-non-import" in outcomes.values()
    assert "no-lexical-binding" in outcomes.values()
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_global_and_method_lookup_never_inherit_enclosing_or_class_import(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from right import pair\n"
        "def outer():\n"
        "    from wrong import pair\n"
        "    def inner():\n"
        "        global pair\n"
        "        return pair(1)\n"
        "    return inner\n"
        "class C:\n"
        "    from wrong import pair\n"
        "    def method(self):\n"
        "        return pair(2)\n"
    )

    rows = [
        row
        for row in lift_rpc._call_contract_demand_rows(tmp_path)
        if row["kind"] == "call-contract-demand"
    ]

    assert [row["targetSymbol"] for row in rows] == [
        "python:right.pair",
        "python:right.pair",
    ]


def test_shadowed_reexport_is_not_published(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_module_exports

    public = tmp_path / "public.py"
    public.write_text("from provider import pair\npair = lambda x: x\n")
    source, _filename, source_cid = path_source(str(public))

    rows = authenticated_module_exports(tmp_path, public, source, source_cid)

    assert not any(row["exportedSymbol"] == "python:public.pair" for row in rows)


def test_try_handler_sees_exceptional_prefix_rebind_and_never_authenticates_import(
    tmp_path,
):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair\n"
        "try:\n"
        "    pair = local\n"
        "    raise E\n"
        "except E:\n"
        "    pair()\n"
    )
    source, _filename, source_cid = path_source(str(consumer))

    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_loop_backedge_rebind_never_authenticates_import_use(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair\n"
        "while cond:\n"
        "    pair()\n"
        "    pair = local\n"
    )
    source, _filename, source_cid = path_source(str(consumer))

    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_spelling_without_authenticated_import_use_has_no_authority(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "def use(pair, pandas_magic):\n" "    pair(1)\n" "    pandas_magic(2)\n"
    )
    source, _filename, source_cid = path_source(str(consumer))
    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert set(outcomes.values()) == {"shadowed-non-import"}


def test_relative_import_is_package_qualified_and_binding_coordinate_is_typed(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    consumer = package / "consumer.py"
    consumer.write_text("from .producer import pair as renamed\nrenamed(1)\n")
    source, _filename, source_cid = path_source(str(consumer))
    rows, _ = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows[0]["targetSymbol"] == "python:pkg.producer.pair"
    use = rows[0]["authenticatedImportUse"]
    assert use["kind"] == "authenticated-import-use"
    assert use["importBindingCid"] == rows[0]["importBindingCid"]
    assert use["cid"].startswith("blake3-512:")


def test_reexport_declaration_is_static_and_source_authenticated(tmp_path):
    (tmp_path / "provider.py").write_text("def pair(x):\n    return (x, x)\n")
    (tmp_path / "public.py").write_text("from provider import pair\n")
    (tmp_path / "consumer.py").write_text(
        "from public import pair as renamed\nrenamed(1)\n"
    )

    rows = lift_rpc._call_contract_demand_rows(tmp_path)
    export = next(
        row for row in rows if row.get("exportedSymbol") == "python:public.pair"
    )
    demand = next(row for row in rows if row["kind"] == "call-contract-demand")

    assert export["targetSymbol"] == "python:provider.pair"
    assert export["sourceCid"].startswith("blake3-512:")
    assert demand["targetSymbol"] == "python:public.pair"
    assert demand["authenticatedImportUse"]["kind"] == "authenticated-import-use"


def test_with_manager_call_is_owned_only_by_context_manager_preconstruction(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "import pytest\n"
        "with pytest.raises(ValueError, match='bad'):\n"
        "    raise ValueError('bad')\n"
    )

    rows = lift_rpc._preconstruction_demand_rows(tmp_path)
    cm_rows = [row for row in rows if row["kind"] == "context-manager-demand"]
    call_rows = [row for row in rows if row["kind"] == "call-contract-demand"]

    assert len(cm_rows) == 1
    assert cm_rows[0]["targetSymbol"] == "pytest.raises"
    assert cm_rows[0]["authenticatedImportUse"]["kind"] == "authenticated-import-use"
    assert call_rows == []


def test_shadowed_local_raises_does_not_inherit_pytest_provider_contract(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from pytest import raises\n"
        "def checked():\n"
        "    raises = lambda *args, **kwargs: object()\n"
        "    with raises(ValueError):\n"
        "        pass\n"
    )

    row = next(
        row
        for row in lift_rpc._preconstruction_demand_rows(tmp_path)
        if row["kind"] == "context-manager-demand"
    )

    assert row["targetSymbol"] is None
    assert row["gapKind"] == "runtime-selected"
    assert "importBindingCid" not in row


def test_import_alias_has_no_parallel_install_source_resolver(monkeypatch):
    from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue

    del monkeypatch
    value = ImportAliasValue("producer.pair", "pair", import_target="producer.pair")

    assert not hasattr(value, "resolve_value")


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
    row = next(
        row
        for row in lift_rpc._call_contract_demand_rows(tmp_path)
        if row["kind"] == "call-contract-demand"
    )
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


def test_only_module_level_function_publishes_import_export_symbol(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        ResolvedContractRefsV1,
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    producer = tmp_path / "producer.py"
    producer.write_text(
        "def pair():\n    return 1\n"
        "class C:\n    def pair(self):\n        return 2\n"
        "def outer():\n    def pair():\n        return 3\n    return pair()\n"
    )
    tree = SourceFile(
        path_source(str(producer)),
        construction_context=TreeConstructionContextV1(
            ResolvedContractRefsV1(CATALOG_CID, TABLE_CID, MappingProxyType({})),
            workspace_root=str(tmp_path),
        ),
    )
    functions = list(tree.functions())

    assert functions[0].sugar().bridge_source_symbol == "python:producer.pair"
    assert functions[1].sugar().bridge_source_symbol is None
    assert functions[2].sugar().bridge_source_symbol == "python:producer.outer"
    assert functions[3].sugar().bridge_source_symbol is None
