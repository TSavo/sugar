"""Enum-style string predicates compose through BoolOp and source returns."""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph


_FUNCTION = (
    "def enum_boundary(name):\n"
    "    return name.startswith('_') and name.endswith('_')\n"
)


def _distribution(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "enum_string_boolop_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(source, encoding="utf-8")
    metadata = root / "enum_string_boolop_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: enum-string-boolop-fixture\n"
        "Version: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "enum_string_boolop_fixture\n", encoding="utf-8"
    )
    recorded = (
        "enum_string_boolop_fixture/__init__.py",
        "enum_string_boolop_fixture-1.0.dist-info/METADATA",
        "enum_string_boolop_fixture-1.0.dist-info/top_level.txt",
        "enum_string_boolop_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _result(tmp_path: Path, expression: str):
    source = _FUNCTION + f"RESULT = {expression}\n" + "after = 1\n"
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path, source))
    module = graph.modules["enum_string_boolop_fixture"]
    after = ast.parse(module.source).body[-1]
    exits = manager_construction._module_prefix_outcome(module, after, graph=graph)
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    return completed.value.context.temporal.value_if_bound("RESULT")


def test_enum_string_predicates_return_the_second_true_operand(tmp_path: Path) -> None:
    """Both closed string methods answer before BoolOp selects its operand."""
    result = _result(tmp_path, "enum_boundary('_member_')")

    assert isinstance(result, TrueBoolLiteralSugar)


def test_false_startswith_short_circuits_and_projects_source_return(
    tmp_path: Path,
) -> None:
    """A false first call crosses the source return and never reads the RHS."""
    result = _result(tmp_path, "enum_boundary('member') and [][1]")

    assert isinstance(result, FalseBoolLiteralSugar)
