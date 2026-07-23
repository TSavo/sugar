from __future__ import annotations

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
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _source_with_resolution(source_identity, resolution):
    first = SourceFile(source_identity)
    with_node = next(node for node in first.nodes() if node.kind in {"With", "AsyncWith"})
    use_site = _coordinate(with_node.items[0].context_expr)
    if callable(resolution):
        resolution = resolution(use_site)
    table = ResolvedContractRefsV1(
        catalog_cid=_cid("c"),
        table_cid=_cid("t"),
        by_use_site=MappingProxyType({use_site: resolution}),
    )
    return SourceFile(
        source_identity,
        construction_context=TreeConstructionContextV1(table),
    )


def _resolved(use_site) -> ContextManagerContractRefV1:
    semantics = ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        catalog_cid=_cid("c"),
        member_cid=_cid("m"),
        payload_cid=_cid("p"),
        bridge_source_symbol="context-manager:dependency.manager",
        import_signature=ImportSignatureV2(()),
        semantics=semantics,
        source_warrant_cids=(_cid("w"),),
    )


def _function_sugar(source_identity, resolution):
    source = _source_with_resolution(source_identity, resolution)
    return next(source.functions()).sugar()


def test_authenticated_ref_constructs_resource_once_and_binds_enter_result(tmp_path, monkeypatch):
    path = tmp_path / "consumer.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager() as entered:\n"
        "        return entered\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    import sugar_lift_py_tests.exit_disposition_proof as source_proof
    from sugar_source_tree.nodes import Call

    manager_constructions = []
    original_call_sugar = Call.sugar

    def count_original_manager(self):
        if self.func.kind == "Name" and self.func.id == "manager":
            manager_constructions.append(self)
        return original_call_sugar(self)

    monkeypatch.setattr(Call, "sugar", count_original_manager)

    monkeypatch.setattr(
        source_proof,
        "prove_exit_disposition_from_manager_expr",
        lambda *_: (_ for _ in ()).throw(AssertionError("source proof invoked")),
    )
    sugar = _function_sugar(path_source(str(path)), _resolved)
    resource = next(statement for statement in sugar.statements if isinstance(statement, WithResourceSugar))
    assert resource.contract_ref.member_cid == _cid("m")
    assert resource.contract_ref.payload_cid == _cid("p")
    assert resource.enter_slot_id == f"{resource.manager_slot_id}#enter_result"
    assert len(manager_constructions) == 1
    bound_return = resource.body[0]
    assert bound_return.value.slot_id == resource.enter_slot_id
    assert bound_return.value.projection == "enter-result"


def test_unresolved_ref_stays_typed_loud(tmp_path, monkeypatch):
    path = tmp_path / "unresolved.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    import sugar_lift_py_tests.exit_disposition_proof as source_proof
    monkeypatch.setattr(source_proof, "prove_exit_disposition_from_manager_expr", lambda *_: pytest.fail("source proof invoked"))

    def unresolved(use_site):
        return ContextManagerResolutionGapV1(
            demand_cid=_cid("d"),
            use_site=use_site,
            target_symbol="context-manager:dependency.manager",
            kind="unresolved-symbol",
            candidate_member_cids=(),
        )

    with pytest.raises(SugarNotWritten) as caught:
        _function_sugar(path_source(str(path)), unresolved)
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert caught.value.kind == "unresolved-symbol"


def test_unsupported_semantics_gap_does_not_construct_resource(tmp_path):
    path = tmp_path / "unsupported.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    def unsupported(use_site):
        return ContextManagerResolutionGapV1(
            demand_cid=_cid("d"),
            use_site=use_site,
            target_symbol="context-manager:dependency.manager",
            kind="unsupported-cm-schema",
            candidate_member_cids=(_cid("m"),),
        )

    with pytest.raises(SugarNotWritten) as caught:
        _function_sugar(path_source(str(path)), unsupported)
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert caught.value.kind == "unsupported-cm-schema"


def test_async_with_stays_typed_loud_even_with_sync_ref(tmp_path):
    path = tmp_path / "async_manager.py"
    path.write_text(
        "from dependency import manager\n"
        "async def f():\n"
        "    async with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    source = _source_with_resolution(path_source(str(path)), _resolved)
    async_with = next(node for node in source.nodes() if node.kind == "AsyncWith")
    with pytest.raises(SugarNotWritten) as caught:
        async_with.sugar()
    assert type(caught.value).__name__ == "AsyncContextManagerUnsupported"


def test_missing_enrolled_resolution_row_is_backend_defect(tmp_path):
    path = tmp_path / "missing_row.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.panic import BackendDefect

    identity = path_source(str(path))
    table = ResolvedContractRefsV1(
        catalog_cid=_cid("c"),
        table_cid=_cid("t"),
        by_use_site=MappingProxyType({}),
    )
    source = SourceFile(identity, construction_context=TreeConstructionContextV1(table))
    with pytest.raises(BackendDefect):
        next(source.functions()).sugar()


def test_multiple_items_and_non_name_binding_stay_typed_loud(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source

    multiple = tmp_path / "multiple.py"
    multiple.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager(), manager():\n"
        "        pass\n"
    )
    first = SourceFile(path_source(str(multiple)))
    with_node = next(node for node in first.nodes() if node.kind == "With")
    rows = {
        _coordinate(item.context_expr): _resolved(_coordinate(item.context_expr))
        for item in with_node.items
    }
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    source = SourceFile(path_source(str(multiple)), construction_context=context)
    with pytest.raises(SugarNotWritten) as caught:
        next(source.functions()).sugar()
    assert type(caught.value).__name__ == "MultipleContextManagerItems"

    target = tmp_path / "target.py"
    target.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager() as (left, right):\n"
        "        pass\n"
    )
    with pytest.raises(SugarNotWritten) as caught:
        _function_sugar(path_source(str(target)), _resolved)
    assert type(caught.value).__name__ == "UnsupportedWithBindingTarget"
