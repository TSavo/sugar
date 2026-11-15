"""SourceUnit definition names / exception-type identity without a second parser.

``definition_name`` and ``exception_type_identity`` must read the
already-materialized typed Module + unit symtable — never a second standard
library parse of the source text. Truthful arms pin the closed lexical
coordinates; lying arms stay loud (``None``).
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


def _definition_names(source: str) -> dict:
    """``{(kind, line, col): definition_name}`` for every def, class and
    lambda of ``source``."""
    sf = _file(source)
    out = {}
    for node in sf.root.walk():
        if node.kind not in ("FunctionDef", "AsyncFunctionDef", "ClassDef", "Lambda"):
            continue
        start = node.line_col_span()
        out[(node.kind, start.start_line, start.start_col)] = sf.unit.definition_name(
            node
        )
    return out


def test_every_definition_is_named_by_its_qualname():
    """CPython's own ``__qualname__``, read off the module walk (#7757): a
    method is named by the class that defines it, a local ``def`` and a lambda
    by their function's ``<locals>`` and their own coordinate."""
    names = _definition_names(
        "def f():\n"
        "    def nested():\n"
        "        pass\n"
        "    return lambda x: x\n"
        "async def g():\n"
        "    pass\n"
        "class C:\n"
        "    def f(self):\n"
        "        pass\n"
        "    key = lambda self: 0\n"
        "if True:\n"
        "    def conditional():\n"
        "        pass\n"
        "h = lambda y: y\n"
        "def k(d=lambda: 0):\n"
        "    return (lambda: z for z in (lambda: [1])())\n"
    )
    assert names == {
        ("FunctionDef", 1, 0): "f",
        ("FunctionDef", 2, 4): "f.<locals>.nested@2:4",
        ("Lambda", 4, 11): "f.<locals>.<lambda>@4:11",
        ("AsyncFunctionDef", 5, 0): "g",
        ("ClassDef", 7, 0): "C",
        ("FunctionDef", 8, 4): "C.f",
        ("Lambda", 10, 10): "C.<lambda>@10:10",
        # A def under a module ``if`` is a module member: what an import of
        # ``conditional`` reaches.
        ("FunctionDef", 12, 4): "conditional",
        ("Lambda", 14, 4): "<lambda>@14:4",
        ("FunctionDef", 15, 0): "k",
        # A default is evaluated in the scope around the ``def``.
        ("Lambda", 15, 8): "<lambda>@15:8",
        # A generator expression is a scope, except for its first iterable.
        ("Lambda", 16, 12): "k.<locals>.<genexpr>.<lambda>@16:12",
        ("Lambda", 16, 32): "k.<locals>.<lambda>@16:32",
    }


def test_a_qualname_two_definitions_share_names_neither_bare():
    """Two definitions of one qualname in one file (a redefined module
    ``def``, a redefined method) are each named by their coordinate: which one
    a reader reaches is the binding at run time, never the bare name."""
    names = _definition_names(
        "def f():\n"
        "    pass\n"
        "def f():\n"
        "    pass\n"
        "class A:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        pass\n"
    )
    assert names == {
        ("FunctionDef", 1, 0): "f@1:0",
        ("FunctionDef", 3, 0): "f@3:0",
        ("ClassDef", 5, 0): "A",
        ("FunctionDef", 6, 4): "A.__init__",
        ("ClassDef", 8, 0): "B",
        ("FunctionDef", 9, 4): "B.__init__",
    }


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

    # A non-builtins import names its target symbol, never the builtin its
    # spelling shares (#7757).
    _sf, name = _raise_name(
        "from elsewhere import TypeError\ndef A():\n    raise TypeError\n",
        "TypeError",
    )
    identity = _sf.unit.exception_type_identity(name)
    assert identity.args[0].value == "import"
    assert identity.args[1].value == "elsewhere.TypeError"

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
    test_every_definition_is_named_by_its_qualname()
    test_a_qualname_two_definitions_share_names_neither_bare()
    test_exception_type_identity_truthful_arms()
    test_exception_type_identity_lying_arms_stay_loud()
    print("ok: source-unit identity without second-parser authority")
