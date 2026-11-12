"""``global`` and ``nonlocal`` statements construct inert sugar.

A ``global`` or ``nonlocal`` declaration binds nothing at construction and
states nothing at reduction: its node's sugar is ``InertSugar``.  Nothing in
the lifter routes a store through the declaration; a store to a declared name
binds in the function's own scope, like any other assignment.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.inert_sugar import InertSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, Global, Nonlocal
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "global_nonlocal.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def test_source_global_constructs_inert_sugar() -> None:
    source = "def f():\n    global x\n    return 1\n"
    tree = _tree(source)
    node = next(n for n in tree.nodes() if isinstance(n, Global))
    sugar = node.sugar()
    assert isinstance(sugar, InertSugar)
    assert node.names == ("x",)


def test_source_nonlocal_constructs_inert_sugar() -> None:
    source = (
        "def outer():\n"
        "    shared = 1\n"
        "    def inner():\n"
        "        nonlocal shared\n"
        "        return shared\n"
        "    return inner()\n"
    )
    tree = _tree(source)
    node = next(n for n in tree.nodes() if isinstance(n, Nonlocal))
    sugar = node.sugar()
    assert isinstance(sugar, InertSugar)
    assert node.names == ("shared",)



def test_source_global_then_assign_statement_kinds() -> None:
    """Source ``global x; x = 1; return x``: Global is InertSugar; Assign separate."""
    source = "def f():\n    global x\n    x = 1\n    return x\n"
    function = next(
        n for n in _tree(source).nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    sugar = function.sugar()
    kinds = [type(s).__name__ for s in sugar.statements]
    assert "InertSugar" in kinds, kinds
    assert "AssignSugar" in kinds or any("Assign" in k for k in kinds), kinds
    global_node = next(n for n in _tree(source).nodes() if isinstance(n, Global))
    assert isinstance(global_node.sugar(), InertSugar)
    assert global_node.names == ("x",)


def test_source_multi_global_names_inert() -> None:
    """``global a, b`` constructs InertSugar with both names."""
    source = "def f():\n    global a, b\n    return 0\n"
    node = next(n for n in _tree(source).nodes() if isinstance(n, Global))
    assert node.names == ("a", "b")
    assert isinstance(node.sugar(), InertSugar)
