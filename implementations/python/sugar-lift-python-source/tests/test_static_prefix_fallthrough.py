"""Static prefix fallthrough: pure-binding AST admits without _module_prefix_outcome.

``prefix_has_completed_fallthrough`` only needs whether control reaches the
export locus.  Pure-binding prefixes (imports, defs, classes, assigns,
TYPE_CHECKING-only Ifs) always fall through under Python module semantics —
MaterializeModule + ClassDef.sugar of every earlier definition was residual
wall (~1.9s of prefix_has_completed_fallthrough on tip 63356a636 for one
pandas/io/json/_json.py open after session memos).

Open-control prefixes (Try/For/Raise/…) still take the full producer.
"""

from __future__ import annotations

import ast
from types import SimpleNamespace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_construction import (
    _module_prefix_outcome,
    _static_prefix_always_fallthrough,
    prefix_has_completed_fallthrough,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _module(source: str, seat: str = "mod.py"):
    return SimpleNamespace(
        source=source,
        source_seat=seat,
        source_cid=blake3_512_of(source.encode("utf-8")),
        module_name="mod",
    )


def _locus_of(source: str, name: str) -> ast.stmt:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return node
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node
    raise AssertionError(f"no locus for {name!r} in source")


def test_static_pure_binding_prefix_admits_without_outcome(monkeypatch) -> None:
    source = (
        "import os\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Callable\n"
        "X = 1\n"
        "class C:\n"
        "    pass\n"
        "def export(value):\n"
        "    return value\n"
    )
    module = _module(source)
    locus = _locus_of(source, "export")
    assert _static_prefix_always_fallthrough(module, locus) is True

    calls = {"n": 0}
    real = _module_prefix_outcome

    def counting(module, locus, **kw):
        calls["n"] += 1
        return real(module, locus, **kw)

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_construction._module_prefix_outcome",
        counting,
    )
    # This tooth has no dependency graph: its authoritative population is empty.
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    assert prefix_has_completed_fallthrough(module, locus, session=session) is True
    assert (
        calls["n"] == 0
    ), f"pure-binding prefix must not run _module_prefix_outcome; n={calls['n']}"


def test_static_open_control_prefix_declines_static_door() -> None:
    source = (
        "import os\n"
        "try:\n"
        "    setup()\n"
        "except Exception:\n"
        "    pass\n"
        "def export(value):\n"
        "    return value\n"
    )
    module = _module(source)
    locus = _locus_of(source, "export")
    assert _static_prefix_always_fallthrough(module, locus) is False


def test_stdlib_graph_still_short_circuits(monkeypatch) -> None:
    source = "def export():\n    return 1\n"
    module = _module(source)
    locus = _locus_of(source, "export")
    graph = SimpleNamespace(artifact_kind="stdlib")
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("stdlib must not reach outcome")

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_construction._module_prefix_outcome",
        boom,
    )
    monkeypatch.setattr(
        "sugar_lift_python_source.manager_construction._static_prefix_always_fallthrough",
        boom,
    )
    assert (
        prefix_has_completed_fallthrough(
            module,
            locus,
            graph=graph,
            session=SourceResolutionSession(enrolled_distributions=frozenset()),
        )
        is True
    )
    assert calls["n"] == 0
