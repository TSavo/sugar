"""Metaclass ``__prepare__`` returns its source-mutated mapping receiver."""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    MappingObjectValue,
    ReceiverFieldStoreValue,
    ReturnValue,
    StringValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.decorated_class_value import MetaclassClassValue
from sugar_lift_py_tests.outcome import Complete, Completed
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph


def _distribution(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "prepare_receiver_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(source, encoding="utf-8")
    metadata = root / "prepare_receiver_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: prepare-receiver-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "prepare_receiver_fixture\n", encoding="utf-8"
    )
    recorded = (
        "prepare_receiver_fixture/__init__.py",
        "prepare_receiver_fixture-1.0.dist-info/METADATA",
        "prepare_receiver_fixture-1.0.dist-info/top_level.txt",
        "prepare_receiver_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


_SOURCE = (
    "class Namespace(dict):\n"
    "    pass\n"
    "class Meta:\n"
    "    def __prepare__(metacls, cls, bases):\n"
    "        namespace = Namespace()\n"
    "        namespace._cls_name = cls\n"
    "        return namespace\n"
    "    def __new__(metacls, cls, bases, namespace):\n"
    "        return namespace\n"
    "class Made(metaclass=Meta):\n"
    "    marker = 7\n"
    "after = 1\n"
)


def _publication(tmp_path: Path):
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path, _SOURCE))
    module = graph.modules["prepare_receiver_fixture"]
    parsed = ast.parse(module.source)
    exits = manager_construction._module_prefix_outcome(
        module, parsed.body[-1], graph=graph
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    published = completed.value.context.temporal.value_if_bound("Made")
    assert isinstance(published, MetaclassClassValue)
    return published.publication


def _raw_prepare_outcome(tmp_path: Path):
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path, _SOURCE))
    module = graph.modules["prepare_receiver_fixture"]
    parsed = ast.parse(module.source)
    made = next(
        statement
        for statement in parsed.body
        if isinstance(statement, ast.ClassDef) and statement.name == "Made"
    )
    exits = manager_construction._module_prefix_outcome(module, made, graph=graph)
    completed = exits.exits[0]
    context = completed.value.context
    meta = context.temporal.value_if_bound("Meta")
    selected = meta.call_method_value(
        "__prepare__",
        (StringValue("Made"), TupleValue(())),
        owner="test_metaclass_prepare_receiver_state",
        blame="prepare-site",
        ctx=context,
    )
    assert isinstance(selected, Complete)
    assert isinstance(selected.value, CallSiteValue)
    return selected.value


def test_prepare_body_emits_receiver_field_store_before_return(tmp_path: Path) -> None:
    callsite = _raw_prepare_outcome(tmp_path)
    retained = callsite._retained_source_completion
    assert retained is not None
    block = retained.value
    assert isinstance(block, BlockValue)
    stores = tuple(
        statement
        for statement in block.statements
        if isinstance(statement, ReceiverFieldStoreValue)
    )
    returns = tuple(
        statement for statement in block.statements if isinstance(statement, ReturnValue)
    )
    assert len(stores) == 1, tuple(
        type(statement).__name__ for statement in block.statements
    )
    assert stores[0].attr == "_cls_name"
    assert stores[0].value == StringValue("Made")
    assert len(returns) == 1
    assert isinstance(returns[0].value, MappingObjectValue)
    assert stores[0].receiver.identity == returns[0].value.identity


def test_type_new_observes_the_post_prepare_namespace(tmp_path: Path) -> None:
    """The pre-store mapping cannot be supplied to either publication face."""
    publication = _publication(tmp_path)

    assert isinstance(publication.namespace_floor, MappingObjectValue)
    assert isinstance(publication.final_class, MappingObjectValue)
    assert publication.final_class.identity == publication.namespace_floor.identity
    for value in (publication.namespace_floor, publication.final_class):
        fields = {field.name: field.value for field in value.fields}
        assert fields["_cls_name"] == StringValue("Made")
