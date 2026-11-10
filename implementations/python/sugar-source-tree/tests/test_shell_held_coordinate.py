"""A shell asks for its construction coordinate once, and the memo stays on the unit.

Every field read, child-edge read and sugar read of a node shell needs the
shell's construction coordinate.  The shell holds the answer and asks
``ConstructionCache.key`` again only when a participant that can be rebound
under it -- the unit's cache, the unit's construction context, the reporter --
is a different object.

Truthful twin: one shell's repeated reads ask for the key once.
Lying twins: a held coordinate is not served after the cache is replaced,
after the reporter is rebound, or after the construction context is rebound;
and holding the coordinate on the shell does not move the memo off the unit.
"""

from __future__ import annotations

import dataclasses
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.construction_cache import ConstructionCache
from sugar_source_tree.reporter import NullReporter
from sugar_source_tree.tree import SourceFile


def _function():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write("def f(x):\n    y = x\n    return y\n")
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _fresh_shell(node):
    """Another shell over the same ref, reporter, control context and unit."""
    shell = dataclasses.replace(node)
    assert shell is not node
    assert shell.ref is node.ref
    return shell


def _key_asks(monkeypatch) -> list[int]:
    asked: list[int] = []
    real = ConstructionCache.key

    def key(self, ref, *args, **kwargs):
        asked.append(id(ref))
        return real(self, ref, *args, **kwargs)

    monkeypatch.setattr(ConstructionCache, "key", key)
    return asked


def _rows_for(cache: ConstructionCache, ref) -> list[tuple]:
    return [key for key in cache.fields if key[0] == id(ref)]


def test_one_shell_asks_for_its_coordinate_once(monkeypatch):
    shell = _fresh_shell(_function())
    asked = _key_asks(monkeypatch)
    for _ in range(5):
        assert shell.name == "f"
    for _ in range(3):
        assert list(shell.children())
    assert asked.count(id(shell.ref)) == 1


def test_two_shells_of_one_coordinate_read_one_row():
    function = _function()
    assert function.name == "f"
    assert list(function.children())
    cache = function.unit.construction_cache
    rows = len(cache.fields)
    shell = _fresh_shell(function)
    assert shell.name == "f"
    assert list(shell.children())
    assert len(cache.fields) == rows
    assert len(_rows_for(cache, function.ref)) == 1


def test_held_coordinate_is_not_served_after_the_cache_is_replaced(monkeypatch):
    shell = _fresh_shell(_function())
    assert shell.name == "f"
    old_cache = shell.unit.construction_cache
    object.__setattr__(shell.unit, "construction_cache", None)
    asked = _key_asks(monkeypatch)
    assert shell.name == "f"
    assert asked.count(id(shell.ref)) == 1
    new_cache = shell.unit.construction_cache
    assert new_cache is not None and new_cache is not old_cache
    assert len(_rows_for(new_cache, shell.ref)) == 1


def test_held_coordinate_is_not_served_after_the_reporter_is_rebound(monkeypatch):
    shell = _fresh_shell(_function())
    assert shell.name == "f"
    cache = shell.unit.construction_cache
    assert len(_rows_for(cache, shell.ref)) == 1
    reporter = NullReporter()
    object.__setattr__(shell, "reporter", reporter)
    asked = _key_asks(monkeypatch)
    assert shell.name == "f"
    assert asked.count(id(shell.ref)) == 1
    rows = _rows_for(cache, shell.ref)
    assert len(rows) == 2
    assert any(key[1] == id(reporter) for key in rows)


def test_held_coordinate_is_not_served_after_the_context_is_rebound(monkeypatch):
    shell = _fresh_shell(_function())
    assert shell.name == "f"
    cache = shell.unit.construction_cache
    assert len(_rows_for(cache, shell.ref)) == 1
    context = object()
    object.__setattr__(shell.unit, "construction_context", context)
    asked = _key_asks(monkeypatch)
    assert shell.name == "f"
    assert asked.count(id(shell.ref)) == 1
    rows = _rows_for(cache, shell.ref)
    assert len(rows) == 2
    assert any(key[2] == id(context) for key in rows)
