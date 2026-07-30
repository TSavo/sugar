"""A source ``__new__`` field store reaches its returned object and consumers."""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
    ReceiverFieldStoreStateSugar,
)
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_source_tree.tree import SourceFile


_SOURCE = (
    "class _NamedIntConstant(int):\n"
    "    def __new__(cls, value, name):\n"
    "        self = super(_NamedIntConstant, cls).__new__(cls, value)\n"
    "        self.name = name\n"
    "        return self\n"
    "\n"
    "ONE = _NamedIntConstant(0, 'FAILURE')\n"
    "RESULT = [op.name for op in [ONE]]\n"
    "after = 1\n"
)


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "named_int_constant_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(_SOURCE, encoding="utf-8")
    metadata = root / "named_int_constant_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: named-int-constant-fixture\n"
        "Version: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "named_int_constant_fixture\n", encoding="utf-8"
    )
    recorded = (
        "named_int_constant_fixture/__init__.py",
        "named_int_constant_fixture-1.0.dist-info/METADATA",
        "named_int_constant_fixture-1.0.dist-info/top_level.txt",
        "named_int_constant_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _module(tmp_path: Path):
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    return graph, graph.modules["named_int_constant_fixture"]


def _field(value: ObjectValue, name: str):
    return next(field.value for field in value.fields if field.name == name)


def test_new_store_transport_reaches_the_constructed_instance(tmp_path: Path) -> None:
    """The emitted receiver-state store cannot disappear during class projection."""
    graph, module = _module(tmp_path)
    parsed = ast.parse(module.source)
    tree = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    class_node = next(
        node
        for node in tree.root.body
        if getattr(node, "kind", None) == "ClassDef"
        and getattr(node, "name", None) == "_NamedIntConstant"
    )
    frame = class_node.source_visible_constructor_frame()
    initializer = frame.body.initializer_body
    assert initializer is not None
    assert len(initializer.statements) == 1
    statement = initializer.statements[0]
    assert isinstance(statement, ExprStatementSugar)
    assert isinstance(statement.value, ReceiverFieldStoreStateSugar)
    assert statement.value.attr == "name"

    result_assignment = next(
        statement
        for statement in parsed.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "RESULT"
            for target in statement.targets
        )
    )
    exits = manager_construction._module_prefix_outcome(
        module, result_assignment, graph=graph
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    instance = completed.value.context.temporal.value_if_bound("ONE")
    assert isinstance(instance, ObjectValue)
    assert _field(instance, "name") == StringValue("FAILURE")


def test_list_comprehension_reads_the_new_assigned_name(tmp_path: Path) -> None:
    """The ordinary consumer reads the field assigned by source ``__new__``."""
    graph, module = _module(tmp_path)
    parsed = ast.parse(module.source)
    after = parsed.body[-1]

    exits = manager_construction._module_prefix_outcome(module, after, graph=graph)

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    result = completed.value.context.temporal.value_if_bound("RESULT")
    assert isinstance(result, ListValue)
    assert result.elements == (StringValue("FAILURE"),)
