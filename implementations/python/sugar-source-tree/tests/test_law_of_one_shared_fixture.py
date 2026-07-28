"""Consumer proof for the explicitly injected shared LAW_OF_ONE evidence."""

import ast
from pathlib import Path

from law_of_one_evidence import LawOfOneEvidence, assert_test_owned_evidence
from law_of_one_fixture import law_of_one_evidence
from law_of_one_symbol_graph import SymbolGraph


def test_shared_law_of_one_evidence_is_typed_sealed_and_closed(
    law_of_one_evidence: LawOfOneEvidence,
) -> None:
    assert assert_test_owned_evidence(law_of_one_evidence) is law_of_one_evidence


def _graph(tmp_path: Path, sources: dict[str, str]) -> SymbolGraph:
    modules = {}
    for module, source in sources.items():
        path = tmp_path / f"{module.replace('.', '_')}.py"
        path.write_text(source, encoding="utf-8")
        modules[module] = (path, ast.parse(source, str(path)))
    return SymbolGraph(modules)


def test_symbol_graph_uses_source_ordered_reaching_definitions(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "m": (
            "def first(): pass\n"
            "def second(): pass\n"
            "def caller(flag, doomed):\n"
            "    target = first\n"
            "    if flag:\n"
            "        target = second\n"
            "    target()\n"
            "    del target\n"
            "    target()\n"
        )
    })
    calls = [edge for edge in graph.calls if edge.expression == "target"]
    assert {target.name for target in calls[0].targets} == {"first", "second"}
    assert calls[0].dynamic is False
    assert calls[1].targets == ()
    assert calls[1].dynamic is True
    assert any("unresolved call edge 'target'" in row for row in graph.discovery_errors)


def test_symbol_graph_does_not_fall_through_a_later_local_rebind(
    tmp_path: Path,
) -> None:
    graph = _graph(tmp_path, {
        "m": (
            "def outer(): pass\n"
            "def caller():\n"
            "    outer()\n"
            "    outer = lambda: None\n"
        )
    })
    call = next(edge for edge in graph.calls if edge.expression == "outer")
    assert call.targets == ()
    assert call.dynamic is True


def test_symbol_graph_resolves_fixed_point_reexports(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "a": "def owner(): pass\n",
        "b": "from a import owner as forwarded\n",
        "c": "from b import forwarded as again\nagain()\n",
    })
    call = next(edge for edge in graph.calls if edge.expression == "again")
    assert {(target.module, target.name) for target in call.targets} == {("a", "owner")}
    assert call.dynamic is False


def test_symbol_graph_resolves_classmethod_cls_to_its_class(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "m": (
            "class SourceFile:\n"
            "    def __init__(self, identity): pass\n"
            "    @classmethod\n"
            "    def from_path(cls, identity):\n"
            "        return cls(identity)\n"
        )
    })
    call = next(edge for edge in graph.calls if edge.expression == "cls")
    assert {(target.name, target.lexical) for target in call.targets} == {
        ("SourceFile", ())
    }
    assert call.dynamic is False
