from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import ObjectValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    construct_manager_behavior,
)


def _installed(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from arbitrary.manager import some_manager\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _resolved(root: Path, source: str):
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    graph = DependencyArtifactGraph.authenticate(_installed(root, source))
    consumer_source = "import arbitrary\narbitrary.some_manager(ExpectedError)\n"
    path = root / "consumer.py"
    path.write_text(consumer_source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        root,
        path,
        consumer_source,
        blake3_512_of(consumer_source.encode()),
    )
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    return graph, resolved


SOURCE = """
class SomeGuard:
    def __init__(self, expected, *, match=None, **observations):
        self.expected = expected
        self.match = match
        self.observations = observations

def helper(expected, *labels, match=None, **observations):
    return SomeGuard(expected, match=match, **observations)

def some_manager(expected, *labels, match=None, **observations):
    return helper(expected, *labels, match=match, **observations)
"""


def test_renamed_factory_constructs_receiver_state_defaults_variadics_and_helpers(
    tmp_path,
):
    graph, resolved = _resolved(tmp_path, SOURCE)
    expected = SymbolicValue(ctor("python:type", [str_const("fixture.Expected")]))
    result = construct_manager_behavior(
        resolved,
        graph=graph,
        positional_actuals=(expected, SymbolicValue(str_const("real-label"))),
        keyword_actuals=(("label", SymbolicValue(str_const("real-entry"))),),
    )

    assert isinstance(result, ConstructedManagerBehaviorV1)
    assert isinstance(result.receiver_state, ObjectValue)
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected"] is expected
    assert fields["match"].to_term(owner="test").name == "None"
    assert result.call_frames[1].definition_name == "helper"
    assert result.formal_actuals[-1].formal_name == "observations"
    assert result.manager_construction_cid.startswith("blake3-512:")
    assert (
        json.loads(json.dumps(result.to_value(), sort_keys=True)) == result.to_value()
    )

    with pytest.raises(ValueError, match="manager construction CID"):
        replace(result, manager_construction_cid="blake3-512:" + "00" * 64)


def test_opaque_factory_stays_typed_loud(tmp_path):
    graph, resolved = _resolved(
        tmp_path, "def some_manager(value):\n    return len(value)\n"
    )
    result = construct_manager_behavior(
        resolved,
        graph=graph,
        positional_actuals=(SymbolicValue(str_const("value")),),
    )
    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind == "opaque-call-target"
