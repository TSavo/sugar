"""Module construction owns one source-ordered block, never child meaning."""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.cpython_adapter import CPythonAstBackend
from sugar_source_tree.nodes import Assert, FunctionDef, Module, Name
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(
    source: str,
    name: str = "module-block.py",
    *,
    backend: CPythonAstBackend | None = None,
) -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        backend=backend,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def test_module_constructs_each_child_once_in_source_order(monkeypatch) -> None:
    tree = _tree(
        "def first():\n"
        "    return 1\n"
        "\n"
        "def second():\n"
        "    return 2\n"
    )
    calls: list[tuple[str, int]] = []
    constructed: dict[str, object] = {}
    original = FunctionDef.sugar

    def observed(child: FunctionDef):
        calls.append((child.name, child.line_col_span().start_line))
        result = original(child)
        constructed[child.name] = result
        return result

    monkeypatch.setattr(FunctionDef, "sugar", observed)

    sugar = tree.root.sugar()

    assert type(sugar).__name__ == "ModuleBlockSugar"
    assert calls == [("first", 1), ("second", 4)]
    assert sugar.statements[0] is constructed["first"]
    assert sugar.statements[1] is constructed["second"]


def test_module_threads_temporal_scope_before_constructing_children(monkeypatch) -> None:
    tree = _tree("x = 1\nassert x == 1\n")
    observed_asserts: list[Assert] = []
    original = Assert.sugar

    def observed(child: Assert):
        observed_asserts.append(child)
        return original(child)

    monkeypatch.setattr(Assert, "sugar", observed)

    sugar = tree.root.sugar()

    assert type(sugar).__name__ == "ModuleBlockSugar"
    assert len(observed_asserts) == 1
    assert not any(
        isinstance(node, Name) and node.id == "x"
        for node in observed_asserts[0].walk()
    )


def test_module_propagates_the_child_owner_panic_and_stops_the_tail(
    monkeypatch,
) -> None:
    tree = _tree(
        "type Alias = int\n"
        "def never_reached():\n"
        "    return 1\n"
    )
    tail_calls = 0
    original = FunctionDef.sugar

    def observed(child: FunctionDef):
        nonlocal tail_calls
        tail_calls += 1
        return original(child)

    monkeypatch.setattr(FunctionDef, "sugar", observed)

    with pytest.raises(SugarNotWritten) as caught:
        tree.root.sugar()

    assert caught.value.owner == "TypeAlias.sugar"
    assert tail_calls == 0


def test_module_block_reduces_to_the_ordinary_block_floor() -> None:
    tree = _tree("pass\npass\n")

    sugar = tree.root.sugar()
    outcome = sugar.desugar()

    assert isinstance(tree.root, Module)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, BlockValue)
    assert outcome.value.can_fall_through is True


def test_backend_materializes_one_module_before_module_block_construction(
    monkeypatch,
) -> None:
    materialized = []
    original = CPythonAstBackend.materialize_module

    def observed(backend, unit, reporter):
        result = original(backend, unit, reporter)
        materialized.append(result)
        return result

    monkeypatch.setattr(CPythonAstBackend, "materialize_module", observed)
    backend = CPythonAstBackend()
    tree = _tree("pass\n", backend=backend)

    sugar = tree.root.sugar()

    assert materialized == [tree.constructed_module]
    assert tree.constructed_module.root is tree.root
    assert type(sugar).__name__ == "ModuleBlockSugar"
