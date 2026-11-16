from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.effect import (
    NameErrorEffect,
    UndeterminedRaiseEffect,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    # A function built from a string literal in a throwaway directory: no
    # workspace exists, and the context says so (never the bare door).
    return next(
        SourceFile(
            path_source(path),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    ).sugar().desugar()


def _entries(source: str):
    # A delete mutates a place through runtime dispatch that can halt, so it
    # partitions the block exactly as an attribute/subscript store does and the
    # body reduces to an ExitSet. These assertions are about the delete the
    # COMPLETED arm records; the halt face and the composition laws live in
    # sugar-lift-py-tests/tests/test_store_outcome_composition.py.
    out = _out(source)
    assert isinstance(out, ExitSet)
    completed = [exit_ for exit_ in out.exits if isinstance(exit_, Completed)]
    assert len(completed) == 1, out.exits
    return completed[0].value.record.statements


@pytest.mark.parametrize(
    ("source", "effect_type"),
    [
        ("def f(d,k):\n del d[k]\n return d\n", UndeterminedRaiseEffect),
    ],
)
def test_store_delete_builds_typed_effect_and_continues(source, effect_type):
    # The delete's own halt is an arm of the body (the dispatched
    # ``__delitem__`` on a formal raises something undetermined), and the
    # block goes on beneath its completed arm to the return.
    out = _out(source)
    assert any(isinstance(halt.effect, effect_type) for halt in out.halts()), out.exits
    entries = _entries(source)
    assert any(type(entry).__name__ == "ReturnValue" for entry in entries)


def test_mixed_delete_uses_tombstone_before_later_target_load() -> None:
    out = _out("def f(o):\n del o, o.attr\n")
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, NameErrorEffect)


@pytest.mark.parametrize("target", ["(a,b)", "[a,b]"])
def test_tuple_and_list_delete_grammar_stays_a_gap(target: str) -> None:
    with pytest.raises(SugarNotWritten):
        _out(f"def f(a,b):\n del {target}\n")


def test_delete_effect_after_halt_is_not_emitted() -> None:
    out = _out("def f(o,E):\n raise E\n del o.attr\n")
    # Every arm halts at the raise (raising a formal may halt more than one
    # way); the delete after it never runs, so no halt is the delete's.
    assert out.halts() == out.exits
    assert out.halts()
    assert not any(
        "delattr" in str(getattr(halt.effect, "producer_node_owner", "")).lower()
        for halt in out.halts()
    ), out.exits
