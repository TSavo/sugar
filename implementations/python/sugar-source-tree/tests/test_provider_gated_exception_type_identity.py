"""Provider-gated import heads close dotted exception-type identity.

Twins for optional-provider patterns that static import binding alone leaves
loud: ``pytest.importorskip`` assignment and ``try: import`` / ``except
ImportError``.  Identity is the sealed coordinate; MRO / ClassValue are not
invented when defining source is absent.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
    AuthenticatedExceptionTypeSugar,
)
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _identity(module_path: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const(module_path)],
    )


def _tree(tmp_path: Path, source: str, name: str = "provider_gate.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return SourceFile(path_source(str(path)))


def _attribute_named(tree: SourceFile, attr: str):
    return next(
        node
        for node in tree.nodes()
        if node.kind == "Attribute" and node.attr == attr
    )


def test_importorskip_attribute_exception_identity_truthful(tmp_path):
    """Truthful: ``pa = pytest.importorskip("pyarrow")`` seals ``pa.ArrowInvalid``."""
    tree = _tree(
        tmp_path,
        "import pytest\n"
        'pa = pytest.importorskip("pyarrow")\n'
        "def f():\n"
        "    return pa.ArrowInvalid\n",
    )
    attr = _attribute_named(tree, "ArrowInvalid")
    assert tree.root.unit.imported_exception_type_identity(attr) == _identity(
        "pyarrow.ArrowInvalid"
    )


def test_try_import_attribute_exception_identity_truthful(tmp_path):
    """Truthful: closed try/import provider gate seals ``pyarrow.ArrowException``."""
    tree = _tree(
        tmp_path,
        "try:\n"
        "    import pyarrow\n"
        "    _HAVE = True\n"
        "except ImportError:\n"
        "    _HAVE = False\n"
        "def f():\n"
        "    return pyarrow.ArrowException\n",
    )
    attr = _attribute_named(tree, "ArrowException")
    assert tree.root.unit.imported_exception_type_identity(attr) == _identity(
        "pyarrow.ArrowException"
    )


def test_static_import_attribute_exception_identity_still_works(tmp_path):
    """Ordinary static import remains the primary door."""
    tree = _tree(
        tmp_path,
        "import pyarrow\n"
        "def f():\n"
        "    return pyarrow.ArrowInvalid\n",
    )
    attr = _attribute_named(tree, "ArrowInvalid")
    assert tree.root.unit.imported_exception_type_identity(attr) == _identity(
        "pyarrow.ArrowInvalid"
    )


def test_reassigned_importorskip_head_stays_loud(tmp_path):
    """Lying: an intervening assignment defeats the provider-gate coordinate."""
    tree = _tree(
        tmp_path,
        "import pytest\n"
        'pa = pytest.importorskip("pyarrow")\n'
        "pa = replacement\n"
        "def f():\n"
        "    return pa.ArrowInvalid\n",
    )
    attr = _attribute_named(tree, "ArrowInvalid")
    assert tree.root.unit.imported_exception_type_identity(attr) is None


def test_parameter_shadow_defeats_provider_gate(tmp_path):
    """Lying: a formal named like the provider head has no import coordinate."""
    tree = _tree(
        tmp_path,
        "import pytest\n"
        'pa = pytest.importorskip("pyarrow")\n'
        "def f(pa):\n"
        "    return pa.ArrowInvalid\n",
    )
    attr = _attribute_named(tree, "ArrowInvalid")
    assert tree.root.unit.imported_exception_type_identity(attr) is None


def test_non_importorskip_assign_stays_loud(tmp_path):
    """Lying: a call that is not importorskip is not a provider gate."""
    tree = _tree(
        tmp_path,
        "import pytest\n"
        'pa = pytest.skip("pyarrow")\n'
        "def f():\n"
        "    return pa.ArrowInvalid\n",
    )
    attr = _attribute_named(tree, "ArrowInvalid")
    assert tree.root.unit.imported_exception_type_identity(attr) is None


def test_try_import_rebind_in_handler_stays_loud(tmp_path):
    """Lying: handler rebinding the module name is not a closed provider gate."""
    tree = _tree(
        tmp_path,
        "try:\n"
        "    import pyarrow\n"
        "except ImportError:\n"
        "    pyarrow = None\n"
        "def f():\n"
        "    return pyarrow.ArrowException\n",
    )
    attr = _attribute_named(tree, "ArrowException")
    assert tree.root.unit.imported_exception_type_identity(attr) is None


def test_authenticated_exception_type_sugar_does_not_force_attribute_floor():
    """Identity-sealed sugar projects without ``SymbolicValue.attribute`` panic."""
    surface = AttributeSugar(
        receiver=NameSugar(name="pa", site=None),
        name="ArrowInvalid",
        site=None,
    )
    sugar = AuthenticatedExceptionTypeSugar(
        surface, _identity("pyarrow.ArrowInvalid"), site=None
    )
    value = sugar.desugar().value
    assert isinstance(value, AuthenticatedExceptionTypeValue)
    assert value.exception_type_identity() == _identity("pyarrow.ArrowInvalid")
    assert value.exception_type_mro() is None
    assert value.class_value is None


def test_live_pandas_arrow_external_error_operands_resolve():
    """The five external_error Arrow attribute operands seal import identity."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    root = authenticated_pandas_corpus().root
    expected = {
        (
            "tests/series/accessors/test_list_accessor.py",
            100,
            "ArrowInvalid",
            "pyarrow.ArrowInvalid",
        ),
        (
            "tests/series/accessors/test_list_accessor.py",
            132,
            "ArrowInvalid",
            "pyarrow.ArrowInvalid",
        ),
        (
            "tests/series/accessors/test_list_accessor.py",
            134,
            "ArrowInvalid",
            "pyarrow.ArrowInvalid",
        ),
        (
            "tests/extension/test_arrow.py",
            1715,
            "ArrowInvalid",
            "pyarrow.ArrowInvalid",
        ),
        (
            "tests/io/test_parquet.py",
            799,
            "ArrowException",
            "pyarrow.ArrowException",
        ),
    }
    found = set()
    for relative, line, attr, qualified in expected:
        path = root / relative
        tree = SourceFile(path_source(str(path)))
        node = next(
            n
            for n in tree.nodes()
            if n.kind == "Attribute"
            and n.attr == attr
            and n.line_col_span().start_line == line
        )
        identity = tree.root.unit.imported_exception_type_identity(node)
        assert identity == _identity(qualified), (relative, line, identity)
        found.add((relative, line, attr, qualified))
    assert found == expected
