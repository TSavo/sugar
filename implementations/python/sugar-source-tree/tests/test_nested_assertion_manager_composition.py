"""Nested assertion managers compose in source order without vendor authority."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExitContractV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
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
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
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


def _resource_ref(use_site, salt: str) -> ContextManagerContractRefV1:
    return _ref(
        use_site,
        ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
        ),
        salt,
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


PINNED_PANDAS_ROOT = Path(
    "/Users/tsavo/sugar-defect-drain/.venv/lib/python3.14/site-packages/pandas"
)
PINNED_DATETIMELIKE_CID = (
    "blake3-512:a8a3afcef87a93452db841a304673c4bca0a52e29e5a63932580a3b638f39300"
    "2003a95d615bfd1bec91d03c90f792b2600a007f5e5c98120c8ca56bb8b79f00"
)
PINNED_INVALID_ARG_CID = (
    "blake3-512:1a2b00ed9faeb66823b5bf57d534f5ec309cdf5201045bf43b199fabd931e597f"
    "f0d207c885c936577ec06e599da93a29f8497c97c1e03b94f3224923e997889"
)
def _real_resource_outer_boundary_inner():
    root = PINNED_PANDAS_ROOT
    if not root.is_dir():
        import pandas

        root = Path(pandas.__file__).resolve().parent
    path = root / "tests/arrays/test_datetimelike.py"
    source = path.read_bytes()
    source_cid = blake3_512_of(source)
    assert source_cid == PINNED_DATETIMELIKE_CID
    identity = (source.decode("utf-8"), str(path), source_cid)
    probe = SourceFile(identity)
    function = next(
        node
        for node in probe.functions()
        if node.name == "test_searchsorted_castable_strings"
    )
    with_nodes = {
        node.line_col_span().start_line: node
        for node in function.walk()
        if node.kind == "With"
    }
    assert set(with_nodes) == {327, 342, 343}
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    rows = {}
    for line, node in with_nodes.items():
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _resource_ref(coordinate, "o")
            if line == 342
            else _ref(coordinate, raise_semantics, "e")
        )
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    built = next(
        node
        for node in SourceFile(identity, construction_context=context).functions()
        if node.name == function.name
    ).sugar()
    outer = None

    def walk(sugar):
        nonlocal outer
        if isinstance(sugar, WithResourceSugar) and sugar.site.line == 342:
            outer = sugar
            return
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(sugar, field, ()) or ():
                walk(child)

    walk(built)
    assert outer is not None
    inner = next(
        child for child in outer.body if isinstance(child, WithEffectBoundarySugar)
    )
    return outer, inner


def test_pinned_resource_outer_assertion_inner_uses_two_authenticated_demands():
    """The concrete 3.0.3 site, never a historical or synthetic substitute."""
    outer, inner = _real_resource_outer_boundary_inner()
    assert isinstance(outer, WithResourceSugar)
    assert isinstance(inner, WithEffectBoundarySugar)
    assert inner in outer.body


def test_pinned_resource_outer_order_is_not_assertion_outer():
    """Lying: swapping the two structural roles must bite on the real site."""
    outer, inner = _real_resource_outer_boundary_inner()
    assert not isinstance(outer, WithEffectBoundarySugar)
    assert not isinstance(inner, WithResourceSugar)


def _real_assertion_outer_resource_inner():
    root = PINNED_PANDAS_ROOT
    if not root.is_dir():
        import pandas

        root = Path(pandas.__file__).resolve().parent
    path = root / "tests/apply/test_invalid_arg.py"
    source = path.read_bytes()
    source_cid = blake3_512_of(source)
    assert source_cid == PINNED_INVALID_ARG_CID
    identity = (source.decode("utf-8"), str(path), source_cid)
    probe = SourceFile(identity)
    function = next(
        node
        for node in probe.functions()
        if node.name == "test_transform_and_agg_err_agg"
    )
    with_nodes = {
        node.line_col_span().start_line: node
        for node in function.walk()
        if node.kind == "With"
    }
    assert set(with_nodes) == {309, 310}
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    rows = {}
    for line, node in with_nodes.items():
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _ref(coordinate, raise_semantics, "x")
            if line == 309
            else _resource_ref(coordinate, "r")
        )
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    built = next(
        node
        for node in SourceFile(identity, construction_context=context).functions()
        if node.name == function.name
    ).sugar()
    outer = None

    def walk(sugar):
        nonlocal outer
        if isinstance(sugar, WithEffectBoundarySugar) and sugar.site.line == 309:
            outer = sugar
            return
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(sugar, field, ()) or ():
                walk(child)

    walk(built)
    assert outer is not None
    inner = next(child for child in outer.body if isinstance(child, WithResourceSugar))
    return outer, inner


def test_pinned_assertion_outer_resource_inner_uses_two_authenticated_demands():
    """The inverse order composes by nesting through the same constructors."""
    outer, inner = _real_assertion_outer_resource_inner()
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(inner, WithResourceSugar)
    assert inner in outer.body


def test_pinned_inverse_order_is_not_resource_outer():
    """Lying: contract kind cannot reorder the two real source occurrences."""
    outer, inner = _real_assertion_outer_resource_inner()
    assert not isinstance(outer, WithResourceSugar)
    assert not isinstance(inner, WithEffectBoundarySugar)
