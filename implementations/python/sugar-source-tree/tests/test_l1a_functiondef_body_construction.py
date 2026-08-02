"""L1a — FunctionDef / FunctionUniverse body construction, one door.

Every method and function walks ``FunctionDef._construct_sugar`` (shared by
``AsyncFunctionDef``). Body statements construct through their children via
``_sugar_body_statement`` → ``stmt.sugar()`` — never a kind ladder on the def.

ClassDef methods (blonde) depend on ``method.sugar()``; this package owns that
path alone.
"""

from __future__ import annotations

import inspect

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar
from sugar_source_tree.nodes import (
    AsyncFunctionDef,
    FunctionDef,
    ClassDef,
)
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "l1a.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _fn(source: str, name: str = "f"):
    tree = _tree(source)
    return next(fn for fn in tree.functions() if fn.name == name)


def test_functiondef_sugar_is_function_universe_with_child_body_statements() -> None:
    """``def f(x): return x`` constructs FunctionUniverseSugar via body children."""
    fn = _fn("def f(x):\n    return x\n")
    assert isinstance(fn, FunctionDef)
    sugar = fn.sugar()
    assert isinstance(sugar, FunctionUniverseSugar)
    assert sugar.name == "f"
    assert sugar.formals == ("x",)
    assert len(sugar.statements) == 1
    assert type(sugar.statements[0]).__name__ == "ReturnSugar"


def test_functiondef_multi_statement_body_constructs_each_child() -> None:
    """Each body statement is its own sugar — child-before-parent, not a bag."""
    fn = _fn("def g(a, b):\n    x = a\n    return x\n", name="g")
    sugar = fn.sugar()
    assert isinstance(sugar, FunctionUniverseSugar)
    kinds = tuple(type(s).__name__ for s in sugar.statements)
    # substitute may inline; body still produced statement sugars.
    assert kinds
    assert all(hasattr(s, "desugar") for s in sugar.statements)


def test_method_sugar_is_function_universe_door() -> None:
    """Class methods walk the same FunctionDef.sugar door blonde will call."""
    tree = _tree("class C:\n    def m(self, x):\n        return x\n")
    cls = next(n for n in tree.nodes() if isinstance(n, ClassDef))
    method = next(b for b in cls.body if isinstance(b, FunctionDef))
    sugar = method.sugar()
    assert isinstance(sugar, FunctionUniverseSugar)
    assert sugar.name == "m"
    assert type(sugar.statements[0]).__name__ == "ReturnSugar"


def test_async_functiondef_shares_function_universe_body_door() -> None:
    """Async def constructs FunctionUniverseSugar — same door, not SugarNotWritten."""
    fn = _fn("async def h(x):\n    return x\n", name="h")
    assert isinstance(fn, AsyncFunctionDef)
    sugar = fn.sugar()
    assert isinstance(sugar, FunctionUniverseSugar)
    assert sugar.name == "h"
    assert sugar.formals == ("x",)
    assert type(sugar.statements[0]).__name__ == "ReturnSugar"


def test_async_functiondef_construct_sugar_delegates_to_functiondef_door() -> None:
    """AsyncFunctionDef does not mint a second FunctionUniverse producer."""
    src = inspect.getsource(AsyncFunctionDef._construct_sugar)
    assert "FunctionDef._construct_sugar" in src
    assert "FunctionUniverseSugar(" not in src
    body_door = inspect.getsource(AsyncFunctionDef._sugar_body_statement)
    assert "FunctionDef._sugar_body_statement" in body_door


def test_body_statement_door_is_stmt_sugar_only() -> None:
    """``_sugar_body_statement`` constructs only via the statement's sugar()."""
    src = inspect.getsource(FunctionDef._sugar_body_statement)
    assert "stmt.sugar()" in src
    # No kind ladder / isinstance bag on the body statement at this door.
    assert "isinstance" not in src
    assert "match " not in src


def test_construct_sugar_routes_body_through_sugar_body_statement() -> None:
    """FunctionUniverse statements are built only through the one body door."""
    src = inspect.getsource(FunctionDef._construct_sugar)
    assert "_sugar_body_statement" in src
    assert "FunctionUniverseSugar(" in src
