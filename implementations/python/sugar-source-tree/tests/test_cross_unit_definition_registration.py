"""RED: source-frame calls retain producer-owned definition registration."""

from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import BackendDefect, ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "def exact(value):\n"
    "    return value\n\n"
    "def other(value):\n"
    "    return value\n\n"
    "result = exact(7)\n"
)


def _identity(source: str = SOURCE, filename: str = "registration.py"):
    return source, filename, blake3_512_of(source.encode())


def _coordinate(call: Call) -> SourceFragmentCoordinateV1:
    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _registered_unit(identity=None):
    identity = _identity() if identity is None else identity
    collector = CollectingReporter()
    source = SourceFile(identity, reporter=collector)
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    definitions = tuple(node for node in root.walk() if isinstance(node, FunctionDef))
    calls = tuple(node for node in root.walk() if isinstance(node, Call))
    assert len(definitions) == 2
    assert len(calls) == 1
    return source, definitions, calls[0], reporter


def _consumer_with_frame(frame, identity=None):
    identity = _identity() if identity is None else identity
    context = TreeConstructionContextV1.for_source_call_construction()
    collector = CollectingReporter()
    source = SourceFile(identity, reporter=collector, construction_context=context)
    original_call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(original_call)] = frame
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    definitions = tuple(node for node in root.walk() if isinstance(node, FunctionDef))
    call = next(node for node in root.walk() if isinstance(node, Call))
    return source, definitions, call, reporter, context


def _manager_frame(tmp_path: Path, name: str):
    package = tmp_path / "reporter_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from reporter_pkg.implementation import {name}\n", encoding="utf-8"
    )
    (package / "implementation.py").write_text(
        f"def {name}(value):\n    return value\n", encoding="utf-8"
    )
    metadata = tmp_path / "reporter_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: reporter-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("reporter_pkg\n", encoding="utf-8")
    recorded = (
        "reporter_pkg/__init__.py",
        "reporter_pkg/implementation.py",
        "reporter_dist-1.0.dist-info/METADATA",
        "reporter_dist-1.0.dist-info/top_level.txt",
        "reporter_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )
    consumer_source = f"from reporter_pkg import {name}\nresult = {name}(7)\n"
    consumer_path = tmp_path / "consumer.py"
    consumer_path.write_text(consumer_source, encoding="utf-8")
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        consumer_path,
        consumer_source,
        blake3_512_of(consumer_source.encode()),
        module_identities={},
    )
    assert len(receipts) == 1
    session = SourceResolutionSession()
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)
    assert isinstance(projected, tuple)
    return projected


@pytest.mark.parametrize("name", ("exact", "unrelated_renamed"))
def test_manager_resolver_returns_exact_reporter_roll_definition(
    tmp_path: Path, name: str
) -> None:
    frame, target = _manager_frame(tmp_path, name)

    assert type(target.reporter) is ConstructionTestimonyReporterV1
    assert target.reporter.materialized_node_for_ref(target.ref) is target
    assert frame.owner is target


def test_cross_unit_call_consumes_exact_producer_definition_registration() -> None:
    producer, definitions, _producer_call, producer_reporter = _registered_unit()
    producer_definition = definitions[0]
    frame = producer_definition.source_visible_call_frame()
    consumer, _consumer_definitions, call, consumer_reporter, context = (
        _consumer_with_frame(frame)
    )

    assert producer.unit.source_cid == consumer.unit.source_cid
    assert producer_reporter.materialized_node_for_ref(producer_definition.ref) is (
        producer_definition
    )
    assert frame.owner.ref is producer_definition.ref
    assert context.source_call_frames[_coordinate(call)] is frame

    sugar = call.sugar()

    assert sugar.expected_definition_ref is producer_definition
    assert sugar.source_call_frame.owner is producer_definition
    assert sugar.call_occurrence == _coordinate(call)
    assert consumer_reporter.materialized_node_for_ref(call.ref) is call


def test_same_roll_definition_registration_remains_lawful() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    collector = CollectingReporter()
    source = SourceFile(_identity(), reporter=collector, construction_context=context)
    definition = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = (
        definition.source_visible_call_frame()
    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    registered_definition = next(
        node for node in root.walk() if isinstance(node, FunctionDef)
    )
    registered_call = next(node for node in root.walk() if isinstance(node, Call))

    sugar = registered_call.sugar()

    assert sugar.expected_definition_ref is registered_definition
    assert sugar.source_call_frame.owner is registered_definition
    assert sugar.call_occurrence == _coordinate(registered_call)


def test_distinct_definition_from_empty_reporter_cannot_authorize_frame() -> None:
    empty_collector = CollectingReporter()
    empty_source = SourceFile(_identity(), reporter=empty_collector)
    empty_definition = next(
        node for node in empty_source.nodes() if isinstance(node, FunctionDef)
    )
    assert not isinstance(empty_definition.reporter, ConstructionTestimonyReporterV1)

    _source, _definitions, call, _reporter, _context = _consumer_with_frame(
        empty_definition.source_visible_call_frame()
    )

    with pytest.raises(BackendDefect) as gap:
        call.sugar()
    assert (
        gap.value.owner == "ConstructionTestimonyReporterV1.retain_registered_node_from"
    )
    assert gap.value.observed == "foreign or absent producer node registration"
    assert gap.value.blame.seal() == empty_definition.fragment.seal()


@pytest.mark.parametrize(
    "axis",
    (
        "foreign-reporter-table-ref",
        "duplicate-rematerialized-definition",
        "wrong-definition-coordinate-scope-owner",
        "foreign-source",
        "reminted-call",
    ),
)
def test_cross_unit_definition_registration_lies_stay_loud(axis) -> None:
    producer, definitions, _producer_call, _producer_reporter = _registered_unit()
    exact_definition, wrong_definition = definitions
    exact_frame = exact_definition.source_visible_call_frame()
    consumer = _consumer_with_frame(exact_frame)
    call, reporter = consumer[2], consumer[3]
    candidate = replace(
        call._construct_sugar(),
        expected_definition_ref=exact_definition,
        call_occurrence=_coordinate(call),
    )

    if axis == "foreign-reporter-table-ref":
        foreign_producer = _registered_unit()
        foreign_frame = foreign_producer[1][0].source_visible_call_frame()
        candidate = replace(
            candidate,
            source_call_frame=foreign_frame,
            source_call_frame_table={_coordinate(call): foreign_frame},
        )
    elif axis == "duplicate-rematerialized-definition":
        duplicate = _registered_unit()
        candidate = replace(candidate, expected_definition_ref=duplicate[1][0])
    elif axis == "wrong-definition-coordinate-scope-owner":
        candidate = replace(candidate, expected_definition_ref=wrong_definition)
    elif axis == "foreign-source":
        foreign_source = SOURCE + "# foreign authenticated bytes\n"
        foreign = _registered_unit(_identity(foreign_source, "foreign.py"))
        candidate = replace(
            candidate,
            expected_definition_ref=foreign[1][0],
            source_call_frame=foreign[1][0].source_visible_call_frame(),
        )
    else:
        reminted = _consumer_with_frame(exact_frame)
        call = reminted[2]
        assert reporter.materialized_node_for_ref(call.ref) is None

    with pytest.raises(ConstructedValueTestimonyNotWritten) as gap:
        reporter.present_construction(call, candidate)
    assert gap.value.owner == "CollectingReporter.present_construction"
    assert "exact typed occurrence" in gap.value.observed
