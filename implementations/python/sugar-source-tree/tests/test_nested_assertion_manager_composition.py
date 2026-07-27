"""Nested assertion managers compose in source order without vendor authority."""

from __future__ import annotations

from types import MappingProxyType

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
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.floor import CallSiteValue, StringValue
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


SOURCE = (
    "from dependency import halting, observing\n"
    "def f():\n"
    '    msg = "unsupported operand type.+for &:"\n'
    '    warn_msg = "deprecated operand"\n'
    "    with halting(TypeError, match=msg):\n"
    "        with observing(FutureWarning, match=warn_msg):\n"
    '            raise TypeError("unsupported operand type for &:")\n'
)

STRESS_SOURCE = (
    "from dependency import observing, halting\n"
    "def f(using_feature):\n"
    "    from dependency import pa\n"
    "    warn = FutureWarning if using_feature else None\n"
    "    if using_feature:\n"
    '        with observing(warn, match="Operation between non"):\n'
    "            with halting(\n"
    "                pa.lib.ArrowNotImplementedError, match=\"has no kernel\"\n"
    "            ):\n"
    '                raise pa.lib.ArrowNotImplementedError("has no kernel")\n'
)

SIGNATURE = ImportSignatureV2(
    (
        CallParameterV1(
            "expected",
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


def _ref(use_site, semantics, salt: str) -> ContextManagerContractRefV1:
    return ContextManagerContractRefV1(
        resolution_cid=_cid(salt),
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
        import_signature=SIGNATURE,
        semantics=semantics,
    )


def _constructed_boundaries(tmp_path, source=SOURCE, *, warning_first=False):
    path = tmp_path / "renamed.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    with_nodes = [node for node in probe.nodes() if node.kind == "With"]
    assert len(with_nodes) == 2
    coordinates = [_coordinate(node.items[0].context_expr) for node in with_nodes]
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    warning_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        WarningEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        WarningObservationBindingV1(),
    )
    semantics = (
        (warning_semantics, raise_semantics)
        if warning_first
        else (raise_semantics, warning_semantics)
    )
    rows = {
        coordinate: _ref(coordinate, selected, salt)
        for coordinate, selected, salt in zip(
            coordinates, semantics, ("r", "q"), strict=True
        )
    }
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(
            _cid("c"), _cid("t"), MappingProxyType(rows)
        )
    )
    function = next(SourceFile(identity, construction_context=context).functions())
    sugar = function.sugar()
    boundaries = []

    def walk(node):
        if isinstance(node, WithEffectBoundarySugar):
            boundaries.append(node)
        for field in (
            "body",
            "statements",
            "entries",
            "then_body",
            "else_body",
        ):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return tuple(boundaries)


def test_variable_patterns_reach_both_nested_boundaries(tmp_path):
    """Truthful: Assign substitution supplies both real ``match=`` operands."""
    outer, inner = _constructed_boundaries(tmp_path)
    outer_call = outer.manager.desugar().value
    inner_call = inner.manager.desugar().value
    assert isinstance(outer_call, CallSiteValue)
    assert isinstance(inner_call, CallSiteValue)
    assert outer_call.arg_values[-1] == StringValue("unsupported operand type.+for &:")
    assert inner_call.arg_values[-1] == StringValue("deprecated operand")


def test_lying_variable_patterns_do_not_alias_between_boundaries(tmp_path):
    """Lying: swapped expectations must fail; the two bindings stay distinct."""
    outer, inner = _constructed_boundaries(tmp_path)
    outer_pattern = outer.manager.desugar().value.arg_values[-1]
    inner_pattern = inner.manager.desugar().value.arg_values[-1]
    assert outer_pattern != inner_pattern


def test_reverse_order_branch_constructs_both_native_boundaries(tmp_path):
    """The stress shape stays source-ordered under a branch and local import."""
    outer, inner = _constructed_boundaries(
        tmp_path, STRESS_SOURCE, warning_first=True
    )
    assert isinstance(outer.semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(inner.semantics.effect_kind, RaiseEffectKindV1)
    assert outer.manager.desugar().value.arg_values[-1] == StringValue(
        "Operation between non"
    )
    inner_call = inner.manager.desugar().value
    assert isinstance(inner_call.arg_values[0], AuthenticatedExceptionTypeValue)
    assert inner_call.arg_values[-1] == StringValue(
        "has no kernel"
    )


def test_reassigned_local_import_head_has_no_exception_identity(tmp_path):
    """Lying: an intervening assignment defeats the import coordinate."""
    source = STRESS_SOURCE.replace(
        "    warn = FutureWarning if using_feature else None\n",
        "    pa = replacement\n"
        "    warn = FutureWarning if using_feature else None\n",
    )
    path = tmp_path / "shadowed.py"
    path.write_text(source, encoding="utf-8")
    tree = SourceFile(path_source(str(path)))
    expected = next(
        node
        for node in tree.nodes()
        if node.kind == "Attribute" and node.attr == "ArrowNotImplementedError"
    )
    assert tree.root.unit.imported_exception_type_identity(expected) is None
