"""RED: CPython call handles must materialize before construction testimony."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _testimony_root(source: SourceFile, collector: CollectingReporter):
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    return materialize(source.unit, source.root.ref, reporter), reporter


def _enum_call() -> tuple[SourceFile, FunctionDef, Call]:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    module = graph.modules["enum"]
    reporter = CollectingReporter()
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid), reporter=reporter
    )
    root, _testimony = _testimony_root(source, reporter)
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == "_is_single_bit"
    )
    call = next(
        node
        for node in root.walk()
        if isinstance(node, Call)
        and node.line_col_span().start_line == 293
        and node.line_col_span().start_col == 19
    )
    assert call.segment() == "_is_single_bit(value)"
    return source, definition, call


def _ordinary_call(tmp_path, *, helper: str, caller: str):
    path = tmp_path / f"{helper}.py"
    path.write_text(
        f"def {helper}(value):\n"
        "    return value\n\n"
        f"def {caller}(value):\n"
        f"    return {helper}(value)\n"
    )
    reporter = CollectingReporter()
    source = SourceFile.from_path(path, reporter=reporter)
    root, testimony = _testimony_root(source, reporter)
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == helper
    )
    call = next(
        node
        for node in root.walk()
        if isinstance(node, Call) and node.segment() == f"{helper}(value)"
    )
    return source, definition, call, testimony


@pytest.mark.parametrize(
    "case",
    ("authenticated-enum", "unrelated-renamed-source"),
)
def test_parser_call_definition_is_materialized_before_reporter_testimony(
    case, tmp_path
) -> None:
    if case == "authenticated-enum":
        source, definition, call = _enum_call()
    else:
        source, definition, call, _reporter = _ordinary_call(
            tmp_path, helper="unrelated_predicate", caller="apply_predicate"
        )

    constructed = call.sugar()

    # The adapter handle is only parser machinery.  The semantic construction
    # carries the exact typed definition occurrence materialized by this unit.
    assert constructed.expected_definition_ref is definition
    assert definition.unit is source.unit
    assert definition.fragment.unit is call.fragment.unit
    assert definition.fragment.seal().source_cid == source.unit.source_cid
    assert definition.kind == "FunctionDef"


def test_raw_or_reminted_parser_handle_never_becomes_semantic_testimony(
    tmp_path,
) -> None:
    _source, _definition, call = _enum_call()
    pre_reporter = call._construct_sugar()
    raw_handle = pre_reporter.expected_definition_ref
    _reminted_source, _reminted_definition, reminted_call, reminted_reporter = (
        _ordinary_call(tmp_path, helper="_is_single_bit", caller="other_call")
    )
    reminted_handle = reminted_call._construct_sugar().expected_definition_ref
    assert reminted_handle is not raw_handle

    # The current offender is retained only to prove the adapter object itself
    # is not the category to admit.  Both the raw occurrence and an independently
    # parsed same-spelling occurrence remain loud at the reporter membrane.
    with pytest.raises(ConstructedValueTestimonyNotWritten) as raw_gap:
        call.reporter.present_construction(call, raw_handle)
    assert "unclassified constructed value category" in str(raw_gap.value)
    assert "cpython_adapter._Handle" in str(raw_gap.value)
    with pytest.raises(ConstructedValueTestimonyNotWritten) as reminted_gap:
        reminted_reporter.present_construction(reminted_call, reminted_handle)
    assert "cpython_adapter._Handle" in str(reminted_gap.value)


@pytest.mark.parametrize(
    "axis",
    ("foreign-source", "wrong-node", "wrong-kind", "method-shaped"),
)
def test_call_definition_testimony_rejects_foreign_or_wrong_occurrence(
    axis, tmp_path
) -> None:
    _source, definition, call, reporter = _ordinary_call(
        tmp_path, helper="predicate", caller="apply"
    )
    truthful = call._construct_sugar()
    foreign_source, foreign_definition, foreign_call, _foreign_reporter = (
        _ordinary_call(tmp_path, helper="predicate", caller="foreign_apply")
    )
    assert foreign_source.unit.source_cid != call.unit.source_cid

    if axis == "foreign-source":
        lie = foreign_definition
    elif axis == "wrong-node":
        lie = foreign_call
    elif axis == "wrong-kind":
        lie = definition.body[0]
    else:
        lie = definition.sugar

    substituted = replace(truthful, expected_definition_ref=lie)
    with pytest.raises(ConstructedValueTestimonyNotWritten) as gap:
        reporter.present_construction(call, substituted)
    assert "CollectingReporter.present_construction" in str(gap.value)
    assert call.unit.filename in str(gap.value)
