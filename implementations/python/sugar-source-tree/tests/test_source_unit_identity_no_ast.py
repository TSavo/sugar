"""SourceUnit module-level / exception-type identity without a second parser.

``is_module_level_function`` and ``exception_type_identity`` must read the
already-materialized typed Module + unit symtable — never a second standard
library parse of the source text. Truthful arms pin the closed lexical
coordinates; lying arms stay loud (``None`` / ``False``).
"""

from __future__ import annotations

import ast as _stdlib_ast
import tempfile
from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _file(source: str) -> SourceFile:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return SourceFile(path_source(path))


def _raise_name(source: str, name: str | None = None):
    sf = _file(source)
    for node in sf.root.walk():
        if node.kind != "Raise":
            continue
        exc = node.exc
        if exc is None:
            continue
        if exc.kind == "Call":
            exc = exc.func
        if exc.kind == "Name" and (name is None or exc.id == name):
            return sf, exc
    raise AssertionError(f"no Raise Name {name!r} in source")


def test_nodes_py_has_no_ast_import_or_parse():
    """R: raw stdlib parse must not be semantic authority in SourceUnit."""
    nodes_path = (
        Path(__file__).resolve().parents[1] / "src" / "sugar_source_tree" / "nodes.py"
    )
    tree = _stdlib_ast.parse(nodes_path.read_text(encoding="utf-8"))
    for node in _stdlib_ast.walk(tree):
        if isinstance(node, _stdlib_ast.Import):
            assert all(alias.name != "ast" for alias in node.names)
        if isinstance(node, _stdlib_ast.ImportFrom):
            assert node.module != "ast"
        if isinstance(node, _stdlib_ast.Attribute) and isinstance(
            node.value, _stdlib_ast.Name
        ):
            if node.value.id == "ast":
                assert node.attr not in ("parse", "walk")


def test_module_level_function_truthful_and_lying():
    sf = _file(
        "def f():\n"
        "    def nested():\n"
        "        pass\n"
        "    pass\n"
        "async def g():\n"
        "    pass\n"
        "class C:\n"
        "    def f(self):\n"
        "        pass\n"
        "if True:\n"
        "    def conditional():\n"
        "        pass\n"
    )
    unit = sf.unit
    by_name_line = {
        (fn.name, fn.line_col_span().start_line): fn for fn in sf.functions()
    }

    # Truthful: direct module-body defs occupy importable slots.
    f_line = next(line for (name, line) in by_name_line if name == "f" and line < 5)
    g_line = next(line for (name, line) in by_name_line if name == "g")
    assert unit.is_module_level_function("f", f_line) is True
    assert unit.is_module_level_function("g", g_line) is True

    # Lying: nested, class method, and conditional-body defs do not.
    nested_line = next(line for (name, line) in by_name_line if name == "nested")
    method_line = next(
        line for (name, line) in by_name_line if name == "f" and line > 5
    )
    conditional_line = next(
        line for (name, line) in by_name_line if name == "conditional"
    )
    assert unit.is_module_level_function("nested", nested_line) is False
    assert unit.is_module_level_function("f", method_line) is False
    assert unit.is_module_level_function("conditional", conditional_line) is False
    # Wrong line for a real module def is also false.
    assert unit.is_module_level_function("f", f_line + 1) is False


def test_exception_type_identity_truthful_arms():
    # Builtin vocabulary, unbound at module level.
    _sf, name = _raise_name("def A():\n    raise ValueError\n", "ValueError")
    identity = _sf.unit.exception_type_identity(name)
    assert identity is not None
    assert identity.name == "python:exception_type_identity"
    assert identity.args[0].value == "builtins"
    assert identity.args[1].value == "ValueError"

    # Exact from-builtins import (including alias).
    _sf, name = _raise_name(
        "from builtins import ValueError as VE\ndef A():\n    raise VE\n",
        "VE",
    )
    identity = _sf.unit.exception_type_identity(name)
    assert identity is not None
    assert identity.args[0].value == "builtins"
    assert identity.args[1].value == "ValueError"

    # One source class definition → source-class coordinate.
    sf, name = _raise_name(
        "class MyErr(Exception):\n    pass\ndef A():\n    raise MyErr\n",
        "MyErr",
    )
    identity = sf.unit.exception_type_identity(name)
    assert identity is not None
    assert identity.args[0].value == "source-class"
    class_def = next(
        n for n in sf.root.walk() if n.kind == "ClassDef" and n.name == "MyErr"
    )
    lc = class_def.line_col_span()
    expected = (
        f"{sf.unit.source_cid}:{lc.start_line}:{lc.start_col}:"
        f"{lc.end_line}:{lc.end_col}"
    )
    assert identity.args[1].value == expected


def test_exception_type_identity_lying_arms_stay_loud():
    # Parameter binding — no identity coordinate.
    _sf, name = _raise_name("def A(ValueError):\n    raise ValueError\n", "ValueError")
    assert _sf.unit.exception_type_identity(name) is None

    # Local reassignment — no identity coordinate.
    _sf, name = _raise_name(
        "def A():\n    ValueError = KeyError\n    raise ValueError\n",
        "ValueError",
    )
    assert _sf.unit.exception_type_identity(name) is None

    # Module-level assignment shadow of a builtin name.
    _sf, name = _raise_name(
        "ValueError = KeyError\ndef A():\n    raise ValueError\n",
        "ValueError",
    )
    assert _sf.unit.exception_type_identity(name) is None

    # Non-builtins import is not a closed exception identity.
    _sf, name = _raise_name(
        "from elsewhere import TypeError\ndef A():\n    raise TypeError\n",
        "TypeError",
    )
    assert _sf.unit.exception_type_identity(name) is None

    # Ambiguous: two module-level bindings for the same name.
    _sf, name = _raise_name(
        "class E(Exception):\n    pass\n"
        "class E(Exception):\n    pass\n"
        "def A():\n    raise E\n",
        "E",
    )
    assert _sf.unit.exception_type_identity(name) is None


if __name__ == "__main__":
    test_nodes_py_has_no_ast_import_or_parse()
    test_module_level_function_truthful_and_lying()
    test_exception_type_identity_truthful_arms()
    test_exception_type_identity_lying_arms_stay_loud()
    print("ok: source-unit identity without second-parser authority")
