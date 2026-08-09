"""Assign aliases and symbolic attribute stores use the sole construction paths."""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


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
    assert (
        second["projected_value"].coordinate.cid != first["source_value"].coordinate.cid
    )


def test_symbolic_attribute_store_in_one_branch_keeps_both_guard_faces():
    # Free undecided receiver + ground-true branch: dual-face RuntimeEffect.
    # Formal receivers mint setattr_named (vertical completion).
    function = _function(
        "def arbitrary(constructed_value):\n"
        "    if True:\n"
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

    # The store is guarded by `predicate` AND it is itself fallible, so the one
    # occurrence has TWO faces: it completed, or it halted. `IfSugar` reduces the
    # branch body to exits and absorbs each one as guarded red testimony, so both
    # faces reach the record -- carrying the same effect under complementary
    # conditions over the store's own outcome coordinate.
    assert len(stores) == 2, [s.branch_conditions for s in stores]
    assert {s.effect for s in stores} == {
        stores[0].effect
    }, "both faces are the SAME store occurrence, not two stores"

    def cites_store_outcome(term):
        if getattr(term, "name", None) == "python:store_completed":
            return True
        return any(cites_store_outcome(a) for a in getattr(term, "args", ()) or ())

    def mentions_store_outcome(formula, negated):
        found = []

        def walk(node, under_not):
            kind = getattr(node, "kind", None)
            if kind == "not":
                for operand in node.operands:
                    walk(operand, not under_not)
                return
            if kind is not None:
                for operand in node.operands:
                    walk(operand, under_not)
                return
            # an atomic formula: check its argument terms
            if any(cites_store_outcome(a) for a in getattr(node, "args", ()) or ()):
                found.append(under_not)

        walk(formula, False)
        return negated in found

    conditions = [s.branch_conditions for s in stores]
    assert all(len(c) == 1 for c in conditions), conditions
    assert any(
        mentions_store_outcome(c[0], False) for c in conditions
    ), "one face must hold where the store COMPLETED"
    assert any(
        mentions_store_outcome(c[0], True) for c in conditions
    ), "the complementary face must hold where the store HALTED"
    assert any(type(entry).__name__ == "ReturnValue" for entry in record)
