"""RED: module-prefix FunctionDefs register before callable publication."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source.manager_construction import _module_prefix_outcome
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter, NullReporter
from sugar_source_tree.tree import SourceFile


def _source(name: str = "exact") -> str:
    return (
        f"def {name}(value):\n"
        "    return value\n\n"
        "prefix_marker = 0\n"
        f"result = {name}(7)\n"
    )


def _module(name: str = "exact") -> AuthenticatedModuleSourceV1:
    source = _source(name)
    return AuthenticatedModuleSourceV1(
        module_name=f"reporter_{name}",
        source_seat=f"reporter_{name}.py",
        source_cid=blake3_512_of(source.encode()),
        source=source,
    )


def _coordinate(call: Call) -> SourceFragmentCoordinateV1:
    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _published_definition(module: AuthenticatedModuleSourceV1, name: str):
    locus = ast.parse(module.source).body[-1]
    exits = _module_prefix_outcome(
        module,
        locus,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    callable_value = completed.value.context.temporal.value_if_bound(name)
    return callable_value.definition


def _consumer(module: AuthenticatedModuleSourceV1, definition: FunctionDef):
    context = TreeConstructionContextV1.for_source_call_construction()
    collector = CollectingReporter()
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        reporter=collector,
        construction_context=context,
    )
    original_call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(original_call)] = (
        definition.source_visible_call_frame()
    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    call = next(node for node in root.walk() if isinstance(node, Call))
    return call, reporter


@pytest.mark.parametrize("name", ("exact", "unrelated_renamed"))
def test_module_prefix_definition_is_registered_before_publication(name) -> None:
    module = _module(name)
    definition = _published_definition(module, name)

    assert type(definition.reporter) is ConstructionTestimonyReporterV1
    assert definition.reporter.materialized_node_for_ref(definition.ref) is definition

    call, consumer_reporter = _consumer(module, definition)
    sugar = call.sugar()

    assert sugar.expected_definition_ref is definition
    assert sugar.call_occurrence == _coordinate(call)
    assert consumer_reporter.materialized_node_for_ref(definition.ref) is definition


def _registered_definition(source: str = "def exact():\n    return 1\n"):
    identity = (source, "registered.py", blake3_512_of(source.encode()))
    collector = CollectingReporter()
    tree = SourceFile(identity, reporter=collector)
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(tree.unit.source_cid)
    )
    root = materialize(tree.unit, tree.root.ref, reporter)
    definition = next(node for node in root.walk() if isinstance(node, FunctionDef))
    return tree, definition, reporter


def test_consumer_retains_the_exact_existing_registered_ref() -> None:
    _tree, definition, producer = _registered_definition()
    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(definition.unit.source_cid)
    )

    retained = consumer.retain_registered_node_from(definition, producer)

    assert retained is definition
    assert consumer.materialized_node_for_ref(definition.ref) is definition


@pytest.mark.parametrize(
    "axis",
    (
        "null-reporter",
        "foreign-reporter-table-ref",
        "late-retroactive-registration",
        "duplicate-rematerialized-definition",
    ),
)
def test_definition_registration_lies_stay_loud(axis) -> None:
    tree, definition, producer = _registered_definition()
    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(tree.unit.source_cid)
    )

    if axis == "null-reporter":
        candidate = definition
        candidate_reporter = NullReporter()
    elif axis == "foreign-reporter-table-ref":
        _foreign_tree, _foreign_definition, candidate_reporter = _registered_definition(
            "def foreign():\n    return 2\n"
        )
        candidate = definition
    elif axis == "late-retroactive-registration":
        source = "def late():\n    return 3\n"
        late_tree = SourceFile(
            (source, "late.py", blake3_512_of(source.encode())),
            reporter=NullReporter(),
        )
        candidate = next(
            node for node in late_tree.nodes() if isinstance(node, FunctionDef)
        )
        candidate_reporter = ConstructionTestimonyReporterV1(
            CollectingReporter(),
            SubstitutionTraceBuilderV1(late_tree.unit.source_cid),
        )
        candidate_reporter.register(candidate)
    else:
        duplicate_reporter = ConstructionTestimonyReporterV1(
            CollectingReporter(), SubstitutionTraceBuilderV1(tree.unit.source_cid)
        )
        duplicate_root = materialize(tree.unit, tree.root.ref, duplicate_reporter)
        candidate = next(
            node for node in duplicate_root.walk() if isinstance(node, FunctionDef)
        )
        candidate_reporter = producer
        assert candidate is not definition
        assert candidate.ref is definition.ref

    with pytest.raises(BackendDefect):
        consumer.retain_registered_node_from(candidate, candidate_reporter)
