"""Module-prefix construction is one reporter/SourceUnit roll."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    ConstructionTestimonyReporterV1,
    constructed_value_cid_v2,
)
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _module(name: str) -> AuthenticatedModuleSourceV1:
    source = (
        f"def {name}(value):\n"
        "    return value\n\n"
        "left, right = (1, 2)\n"
        "prefix_marker = 0\n"
    )
    return AuthenticatedModuleSourceV1(
        module_name=f"one_roll_{name}",
        source_seat=f"one_roll_{name}.py",
        source_cid=blake3_512_of(source.encode()),
        source=source,
    )


def _observe_prefix(monkeypatch, name: str):
    module = _module(name)
    observed = []

    class RecordingSourceFile(SourceFile):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            observed.append(self)

    monkeypatch.setattr(manager_construction, "SourceFile", RecordingSourceFile)
    locus = ast.parse(module.source).body[-1]
    manager_construction._module_prefix_outcome(
        module,
        locus,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    assert len(observed) == 1
    return observed[0]


@pytest.mark.parametrize("name", ("exact", "unrelated_renamed"))
def test_module_prefix_tables_are_from_one_reporter_roll(monkeypatch, name) -> None:
    source_file = _observe_prefix(monkeypatch, name)
    unit = source_file.unit
    reporter = source_file.reporter

    assert type(reporter) is ConstructionTestimonyReporterV1
    assert source_file.root.reporter is reporter
    assert source_file.constructed_module.reporting_projection is reporter
    assert source_file.constructed_module.root is source_file.root
    assert unit.typed_module is source_file.root

    functions = source_file.constructed_module.function_nodes
    assert functions == unit.function_nodes
    assert len(functions) == 1
    assert isinstance(functions[0], FunctionDef)
    assert functions[0] is source_file.root.body[0]
    assert functions[0].reporter is reporter

    for rows in unit.module_direct_bindings.values():
        for binding in rows:
            assert binding in source_file.root.body
            assert binding.reporter is reporter
            assert binding.unit is unit

    assign = source_file.root.body[1]
    patterns = unit.require_target_patterns(assign)
    assert len(patterns) == 1
    assert patterns[0].consumer_occurrence is assign
    assert patterns[0].source_unit is unit
    assert unit.target_pattern_construction_count == 1

    receipt = source_file.constructed_module.construction_event_receipt
    assert (
        constructed_value_cid_v2(receipt) == source_file.construction_event_receipt_cid
    )
    with pytest.raises(ConstructedValueCategoryGap):
        constructed_value_cid_v2(source_file.constructed_module)


def test_module_prefix_rejects_every_two_roll_cross_wire(monkeypatch) -> None:
    exact = _observe_prefix(monkeypatch, "cross_wire")
    foreign = SourceFile(
        (
            _module("foreign").source,
            _module("foreign").source_seat,
            _module("foreign").source_cid,
        )
    )

    # These are the bounded manifestations of a second materialization roll:
    # stale NULL-reporter bindings, a duplicate raw root, and foreign
    # reporter/context/source/locus testimony.  None may inhabit the one-roll
    # tables seated on the exact SourceUnit.
    stale = tuple(
        binding
        for rows in exact.unit.module_direct_bindings.values()
        for binding in rows
        if binding.reporter is not exact.reporter
    )
    assert stale == ()
    assert exact.constructed_module.root is exact.root
    assert exact.root.unit is exact.unit
    assert all(node.reporter is exact.reporter for node in exact.unit.function_nodes)
    assert all(node.unit is exact.unit for node in exact.unit.function_nodes)
    assert all(node is not foreign.root for node in exact.unit.function_nodes)
    assert all(
        node.fragment is not foreign.root.fragment for node in exact.unit.function_nodes
    )
