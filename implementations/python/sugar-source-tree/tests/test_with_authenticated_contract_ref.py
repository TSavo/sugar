from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
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
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, RaiseEffect
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
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
    with_node = next(
        node for node in first.nodes() if node.kind in {"With", "AsyncWith"}
    )
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
        use_site_cid=_hash_json(use_site.wire()),
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
        semantics=semantics,
    )


def _function_sugar(source_identity, resolution):
    source = _source_with_resolution(source_identity, resolution)
    return next(source.functions()).sugar()


def _effect_resolved(use_site) -> ContextManagerContractRefV1:
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected_exception",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "match",
                PrimitiveSort("String"),
                KeywordOnlyV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
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
        import_signature=signature,
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            OptionalFormalArgumentProjectionV1(1),
            ExceptionInfoBindingV1(),
        ),
    )


@pytest.mark.parametrize(
    ("body", "result_type", "effect_type"),
    [
        ('raise ValueError("boom")', Completed, None),
        ('raise TypeError("boom")', Halted, RaiseEffect),
        ("pass", Halted, ExpectationNotMetEffect),
    ],
)
def test_effect_boundary_projects_real_call_actuals_and_routes_exitset(
    tmp_path, body, result_type, effect_type
):
    path = tmp_path / "pytest_boundary.py"
    path.write_text(
        "from pytest import raises as expect_raises\n"
        "def f():\n"
        '    with expect_raises(ValueError, match="boom"):\n'
        f"        {body}\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    outcome = boundary.desugar()
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    if result_type is Completed:
        assert isinstance(face, Completed)
    else:
        assert isinstance(face, Halted)
        assert isinstance(face.effect, effect_type)


def _effect_boundary_face(tmp_path, source):
    path = tmp_path / "identity_boundary.py"
    path.write_text(source)
    from sugar_lift_python_source.source_oracle import path_source

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    outcome = boundary.desugar()
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    return outcome.exits[0]


def test_effect_boundary_matches_builtin_exception_alias_by_identity(tmp_path):
    face = _effect_boundary_face(
        tmp_path,
        "from builtins import ValueError as VE\n"
        "from pytest import raises\n"
        "def f():\n"
        "    with raises(VE):\n"
        "        raise ValueError('boom')\n",
    )
    assert isinstance(face, Completed)


def test_effect_boundary_does_not_match_distinct_same_spelling_type(tmp_path):
    face = _effect_boundary_face(
        tmp_path,
        "from builtins import ValueError as BuiltinVE\n"
        "from pytest import raises\n"
        "class ValueError(Exception):\n"
        "    pass\n"
        "def f():\n"
        "    with raises(ValueError):\n"
        "        raise BuiltinVE('boom')\n",
    )
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)


def test_effect_boundary_without_exception_identity_stays_loud(tmp_path):
    path = tmp_path / "unknown_identity.py"
    path.write_text(
        "from pytest import raises\n"
        "def f(expected):\n"
        "    with raises(expected):\n"
        "        raise ValueError('boom')\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    with pytest.raises(SugarNotWritten, match="authenticated exception-type identity"):
        boundary.desugar()


def test_authenticated_ref_constructs_resource_once_and_binds_enter_result(
    tmp_path, monkeypatch
):
    path = tmp_path / "consumer.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager() as entered:\n"
        "        return entered\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import Call

    manager_constructions = []
    original_call_sugar = Call.sugar

    def count_original_manager(self):
        if self.func.kind == "Name" and self.func.id == "manager":
            manager_constructions.append(self)
        return original_call_sugar(self)

    monkeypatch.setattr(Call, "sugar", count_original_manager)

    # Authenticated contract-ref path only — raw-AST exit_disposition_proof is gone.
    sugar = _function_sugar(path_source(str(path)), _resolved)
    resource = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithResourceSugar)
    )
    assert resource.contract_ref.contract_cid == _cid("m")
    assert resource.contract_ref.payload_cid == _cid("p")
    assert resource.enter_slot_id == f"{resource.manager_slot_id}#enter_result"
    assert len(manager_constructions) == 1
    bound_return = resource.body[0]
    assert bound_return.value.slot_id == resource.enter_slot_id
    assert bound_return.value.projection == "enter-result"


def test_unresolved_ref_stays_typed_loud(tmp_path):
    path = tmp_path / "unresolved.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

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
