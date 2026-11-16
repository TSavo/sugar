"""Assign aliases and symbolic attribute stores use the sole construction paths."""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import _ground_value
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

    # The alias reads the binding the original holds (a reference re-spanned
    # to the read's own site, #7661): both resolve to the ONE literal
    # occurrence assigned, never a parallel copy of it.
    alias = _ground_value(second["renamed"].state)
    held = _ground_value(first["original"].state)
    assert alias is not None and held is not None
    assert alias.fragment.seal().cid == held.fragment.seal().cid
    assert second["renamed"].coordinate.cid != first["original"].coordinate.cid


def test_renamed_alias_has_the_same_single_binding_path():
    function = _function(
        "def arbitrary():\n"
        "    source_value = 7\n"
        "    projected_value = source_value\n"
        "    return projected_value\n"
    )
    first, second, *_ = _runtime_entries(function)

    # The alias reads the binding the original holds (a reference re-spanned
    # to the read's own site, #7661): both resolve to the ONE literal
    # occurrence assigned, never a parallel copy of it.
    alias = _ground_value(second["projected_value"].state)
    held = _ground_value(first["source_value"].state)
    assert alias is not None and held is not None
    assert alias.fragment.seal().cid == held.fragment.seal().cid
    assert (
        second["projected_value"].coordinate.cid != first["source_value"].coordinate.cid
    )


def test_symbolic_attribute_store_in_one_branch_keeps_both_guard_faces():
    # Free undecided receiver (a name only an unread star import may bind) +
    # ground-true branch: the one undecided attribute mutation, as a formal
    # receiver's store is (``store_effect_sugar.attribute_mutation``).
    function = _function(
        "from unread_module import *\n"
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

    def store_atom(formula):
        # The one undecided attribute mutation's completes atom (#7757 NEW-4).
        return getattr(formula, "name", None) == "python:setattr.completes"

    (done,) = completed
    (stopped,) = halted
    assert store_atom(done.guard), "the completed face holds where the store COMPLETED"
    assert getattr(stopped.guard, "kind", None) == "not"
    assert store_atom(stopped.guard.operands[0]), "the halted face holds where the store HALTED"

    # The halted face raises something undetermined; both faces are the SAME
    # store occurrence by the one atom their guards cite.
    assert isinstance(stopped.effect, UndeterminedRaiseEffect)
    assert stopped.effect.producer_node_owner == "UndecidedSetattr"
    assert stopped.guard.operands[0] == done.guard
    record = done.value.record.statements
    assert any(type(entry).__name__ == "ReturnValue" for entry in record)
