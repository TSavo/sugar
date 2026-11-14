from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.effect import (
    AttributeDeleteRuntimeEffect,
    NameErrorEffect,
    RaiseEffect,
    SubscriptDeleteRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


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


def _halt_effects(entries) -> list:
    """The effects of the recorded entries in which every arm halts."""
    return [
        halt.effect
        for entry in entries
        if isinstance(entry, ExitSet) and entry.halts() == entry.exits
        for halt in entry.halts()
    ]


@pytest.mark.parametrize(
    ("source", "effect_type"),
    [
        ("def f(o):\n del o.attr\n return o\n", AttributeDeleteRuntimeEffect),
        ("def f(d,k):\n del d[k]\n return d\n", SubscriptDeleteRuntimeEffect),
    ],
)
def test_store_delete_builds_typed_effect_and_continues(source, effect_type):
    entries = _entries(source)
    effects = _halt_effects(entries)
    assert len(effects) == 1
    assert isinstance(effects[0], effect_type)
    assert any(type(entry).__name__ == "ReturnValue" for entry in entries)


def test_multi_target_delete_effects_preserve_source_order() -> None:
    entries = _entries("def f(o,d,k):\n del o.attr, d[k]\n return o\n")
    effects = _halt_effects(entries)
    assert [type(effect) for effect in effects] == [
        AttributeDeleteRuntimeEffect,
        SubscriptDeleteRuntimeEffect,
    ]


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
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert not isinstance(halt.effect, AttributeDeleteRuntimeEffect)
