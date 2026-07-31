"""A metaclass-prepared namespace receives the source class body in order."""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import MappingObjectValue, ObjectMethodValue, StringValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph


SOURCE = (
    "class Namespace(dict):\n"
    "    def __setitem__(self, key, value):\n"
    "        return super().__setitem__(key, value)\n"
    "class Meta:\n"
    "    def __prepare__(metacls, name, bases):\n"
    "        return Namespace()\n"
    "    def __new__(metacls, name, bases, namespace):\n"
    "        return namespace\n"
    "class Published(metaclass=Meta):\n"
    "    FIRST = 1\n"
    "    def member(self):\n"
    "        return 2\n"
    "    LAST = 3\n"
    "after = Published\n"
)


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "metaclass_namespace_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(SOURCE, encoding="utf-8")
    metadata = root / "metaclass_namespace_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: metaclass-namespace-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "metaclass_namespace_fixture\n", encoding="utf-8"
    )
    recorded = (
        "metaclass_namespace_fixture/__init__.py",
        "metaclass_namespace_fixture-1.0.dist-info/METADATA",
        "metaclass_namespace_fixture-1.0.dist-info/top_level.txt",
        "metaclass_namespace_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _prefix(tmp_path: Path):
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    module = graph.modules["metaclass_namespace_fixture"]
    locus = ast.parse(SOURCE).body[-1]
    exits = manager_construction._module_prefix_outcome(
        module, locus, graph=graph
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    return completed


def _assert_source_body_roster(writes: tuple[tuple[str, object], ...]) -> None:
    assert tuple(name for name, _value in writes) == ("FIRST", "member", "LAST")
    assert isinstance(writes[1][1], ObjectMethodValue)
    assert writes[1][1].name == "member"


def test_prepared_namespace_receives_every_body_member_in_source_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truthful arm: each body member uses the prepared receiver's source door."""
    writes: list[tuple[str, object]] = []
    original = MappingObjectValue.setitem_with_context

    def record_source_setitem(self, index, value, site, ctx):
        assert isinstance(index, StringValue)
        writes.append((index.value, value))
        return original(self, index, value, site, ctx)

    monkeypatch.setattr(
        MappingObjectValue, "setitem_with_context", record_source_setitem
    )

    completed = _prefix(tmp_path)
    published = completed.value.context.temporal.value_if_bound("Published")
    namespace = published.publication.namespace_floor

    assert isinstance(namespace, MappingObjectValue)
    _assert_source_body_roster(tuple(writes))
    assert tuple(key.value for key, _value in namespace.entries) == (
        "FIRST",
        "member",
        "LAST",
    )
    assert namespace.entries[1][1] is writes[1][1]


def test_bypassing_source_setitem_cannot_publish_the_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lying arm: a direct mapping copy cannot stand in for source dispatch."""

    class SourceSetitemReached(RuntimeError):
        pass

    def stop_at_source_setitem(self, index, value, site, ctx):
        del self, index, value, site, ctx
        raise SourceSetitemReached

    monkeypatch.setattr(
        MappingObjectValue, "setitem_with_context", stop_at_source_setitem
    )

    with pytest.raises(SourceSetitemReached):
        _prefix(tmp_path)


def test_body_roster_tooth_rejects_an_omitted_method() -> None:
    """Lying arm: preserving fields while dropping the method cannot pass."""
    with pytest.raises(AssertionError):
        _assert_source_body_roster((("FIRST", object()), ("LAST", object())))
