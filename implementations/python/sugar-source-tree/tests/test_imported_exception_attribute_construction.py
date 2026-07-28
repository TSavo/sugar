"""Import-bound dotted exception types construct without Attribute projection.

Mechanism: ``imported_exception_type_identity`` joins the authenticated import
target with the static Attribute chain into one
``python:exception_type_identity(import, qualified)`` coordinate.  The CM
contract authenticates the operand's *role* as an exception type; this module
authenticates only the identity.  ``AuthenticatedExceptionTypeSugar`` projects
that coordinate as ``ExceptionClassValue`` and never re-asks the opaque module
receiver for a member (no spelling table, no ``py.getattr`` invent).

Pinned pandas residual (Owner 3 — external exception coordinates):

- four ``pa.ArrowInvalid`` With heads
- one ``pyarrow.ArrowException`` With head

Each site either routes with a matching authenticated type operand, or keeps a
later residual that is *not* ``SymbolicValue.attribute`` on the exception name.
"""

from __future__ import annotations

from pathlib import Path
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
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

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


def _raise_semantics():
    return EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )


def _ref(use_site, salt: str) -> ContextManagerContractRefV1:
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
        semantics=_raise_semantics(),
    )


def _boundary(tmp_path: Path, source: str) -> WithEffectBoundarySugar:
    path = tmp_path / "site.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    with_node = next(node for node in probe.nodes() if node.kind == "With")
    coordinate = _coordinate(with_node.items[0].context_expr)
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(
            _cid("c"), _cid("t"), MappingProxyType({coordinate: _ref(coordinate, "r")})
        )
    )
    function = next(SourceFile(identity, construction_context=context).functions())
    sugar = function.sugar()
    boundaries: list[WithEffectBoundarySugar] = []

    def walk(node) -> None:
        if isinstance(node, WithEffectBoundarySugar):
            boundaries.append(node)
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(node, field, ()) or ():
                walk(child)
        manager = getattr(node, "manager", None)
        if manager is not None:
            walk(manager)

    walk(sugar)
    assert len(boundaries) == 1
    return boundaries[0]


def _attribute(tree: SourceFile, attr: str):
    return next(
        node for node in tree.nodes() if node.kind == "Attribute" and node.attr == attr
    )


def test_import_alias_arrow_invalid_identity_is_import_coordinate(tmp_path):
    """Truthful: ``import pyarrow as pa`` + ``pa.ArrowInvalid`` is one import identity."""
    path = tmp_path / "alias.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.imported_exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )


def test_module_name_arrow_exception_identity_is_import_coordinate(tmp_path):
    """Truthful: bare ``import pyarrow`` + ``pyarrow.ArrowException`` is closed."""
    path = tmp_path / "mod.py"
    path.write_text(
        "import pyarrow\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.imported_exception_type_identity(
        _attribute(tree, "ArrowException")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )


def test_import_bound_exception_desugars_to_authenticated_type(tmp_path):
    """Truthful twin: manager arg is AuthenticatedExceptionTypeValue, not Attribute."""
    boundary = _boundary(
        tmp_path,
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
    )
    call = boundary.manager.desugar().value
    expected = call.arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )
    assert isinstance(expected.value, ExceptionClassValue)
    assert expected.value.qualified_name == "pyarrow.ArrowInvalid"


def test_arrow_exception_module_attr_desugars_to_authenticated_type(tmp_path):
    """Truthful twin for the parquet residual spelling ``pyarrow.ArrowException``."""
    boundary = _boundary(
        tmp_path,
        "import pyarrow\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
    )
    expected = boundary.manager.desugar().value.arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )
    assert isinstance(expected.value, ExceptionClassValue)
    assert expected.value.qualified_name == "pyarrow.ArrowException"


def test_nested_lib_export_uses_full_import_chain(tmp_path):
    """Mechanism: every static Attribute link joins the import coordinate."""
    path = tmp_path / "nested.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.lib.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.imported_exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.lib.ArrowInvalid")],
    )


def test_reassigned_import_head_has_no_exception_identity(tmp_path):
    """Lying twin: an intervening assignment defeats the import coordinate."""
    path = tmp_path / "shadowed.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f(replacement):\n"
        "    pa = replacement\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    assert (
        tree.unit.imported_exception_type_identity(_attribute(tree, "ArrowInvalid"))
        is None
    )


def test_no_pyarrow_spelling_arm_in_authenticator():
    """Guard: the desugar path never branches on vendor exception spellings."""
    from pathlib import Path

    sugar_path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "authenticated_exception_type_sugar.py"
    )
    text = sugar_path.read_text(encoding="utf-8")
    for forbidden in (
        "ArrowInvalid",
        "ArrowException",
        "pyarrow",
        "ArrowNotImplemented",
    ):
        assert forbidden not in text, forbidden


def test_importorskip_binding_authenticates_arrow_invalid(tmp_path):
    """Truthful: ``pa = pytest.importorskip("pyarrow")`` is an import binding."""
    path = tmp_path / "skip.py"
    path.write_text(
        "import pytest\n"
        'pa = pytest.importorskip("pyarrow")\n'
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.imported_exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )
    sugar = _attribute(tree, "ArrowInvalid").sugar()
    from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar

    assert isinstance(sugar, ImportMemberSugar)
    assert sugar.qualified_name == "pyarrow.ArrowInvalid"
    floor = sugar.desugar().value
    assert floor.exception_type_identity() == identity


def test_try_import_optional_binding_authenticates_module_attr(tmp_path):
    """Truthful: try/import with unbound except path keeps the ImportDef alone."""
    path = tmp_path / "tryimp.py"
    path.write_text(
        "try:\n"
        "    import pyarrow\n"
        "except ImportError:\n"
        "    pass\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.imported_exception_type_identity(
        _attribute(tree, "ArrowException")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )


def test_try_import_with_except_rebind_stays_loud(tmp_path):
    """Lying: except rebinding the name defeats unique import identity."""
    path = tmp_path / "try_rebind.py"
    path.write_text(
        "try:\n"
        "    import pyarrow\n"
        "except ImportError:\n"
        "    pyarrow = None\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    assert (
        tree.unit.imported_exception_type_identity(_attribute(tree, "ArrowException"))
        is None
    )
