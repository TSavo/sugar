"""Assign aliases and symbolic attribute stores use the sole construction paths."""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _runtime_entries(function):
    trace = function.sugar().substitution_trace
    return [dict(record.post_bindings) for record in trace.records]


def test_alias_copies_the_authenticated_live_value_without_parallel_identity():
    function = _function(
        "def arbitrary():\n"
        "    original = 7\n"
        "    renamed = original\n"
        "    return renamed\n"
    )
    first, second, *_ = _runtime_entries(function)

    assert second["renamed"].state.ref is first["original"].state.ref
    assert (
        second["renamed"].state.fragment.seal().cid
        == first["original"].state.fragment.seal().cid
    )
    assert second["renamed"].coordinate.cid != first["original"].coordinate.cid


def test_renamed_alias_has_the_same_single_binding_path():
    function = _function(
        "def arbitrary():\n"
        "    source_value = 7\n"
        "    projected_value = source_value\n"
        "    return projected_value\n"
    )
    first, second, *_ = _runtime_entries(function)

    assert second["projected_value"].state.ref is first["source_value"].state.ref
    assert (
        second["projected_value"].state.fragment.seal().cid
        == first["source_value"].state.fragment.seal().cid
    )
    assert second["projected_value"].coordinate.cid != first["source_value"].coordinate.cid


def test_symbolic_attribute_store_in_one_branch_keeps_both_guard_faces():
    function = _function(
        "def arbitrary(predicate, symbolic_receiver, constructed_value):\n"
        "    if predicate:\n"
        "        symbolic_receiver.payload = constructed_value\n"
        "    return constructed_value\n"
    )
    outcome = function.sugar().desugar()
    assert isinstance(outcome, Complete)
    record = outcome.value.record.statements
    stores = [
        entry
        for entry in record
        if isinstance(entry, Incomplete)
        and isinstance(entry.effect, AttributeStoreRuntimeEffect)
    ]

    assert len(stores) == 1
    assert len(stores[0].branch_conditions) == 1
    assert any(type(entry).__name__ == "ReturnValue" for entry in record)
