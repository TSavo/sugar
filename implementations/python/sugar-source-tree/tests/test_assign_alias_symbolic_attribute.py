"""Assign aliases and symbolic attribute stores use the sole construction paths."""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
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

    # The store is fallible, so the one occurrence has TWO faces: it completed,
    # or it halted.  The decided ``if`` hands back its suite's own faces, so the
    # halted face is a real halt -- the function does NOT go on to return there
    # -- and only the completed face carries the return.
    assert isinstance(outcome, ExitSet)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert len(completed) == 1 and len(halted) == 1, outcome.exits

    def cites_store_outcome(term):
        if getattr(term, "name", None) == "python:store_completed":
            return True
        return any(cites_store_outcome(a) for a in getattr(term, "args", ()) or ())

    def store_atom(formula):
        return getattr(formula, "name", None) == "py.truthy" and any(
            cites_store_outcome(a) for a in formula.args
        )

    (done,) = completed
    (stopped,) = halted
    assert store_atom(done.guard), "the completed face holds where the store COMPLETED"
    assert getattr(stopped.guard, "kind", None) == "not"
    assert store_atom(stopped.guard.operands[0]), "the halted face holds where the store HALTED"

    record = done.value.record.statements
    stores = [
        halt
        for entry in record
        if isinstance(entry, ExitSet) and entry.halts() == entry.exits
        for halt in entry.halts()
        if isinstance(halt.effect, AttributeStoreRuntimeEffect)
    ]
    assert len(stores) == 1
    assert isinstance(stopped.effect, AttributeStoreRuntimeEffect)
    assert stopped.effect == stores[0].effect, "both faces are the SAME store occurrence"
    assert any(type(entry).__name__ == "ReturnValue" for entry in record)
