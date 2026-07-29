from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import DictValue, FloorValue, StringValue, TermValue
from sugar_lift_py_tests.ir import atomic, ctor
from sugar_lift_py_tests.outcome import Complete, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, complement_guard
from sugar_lift_py_tests.sugar.subscript_sugar import SubscriptSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _ValueSugar(ConstructedTermSugar):
    outcome: object
    site: object

    @classmethod
    def witnesses(cls):
        raise NotImplementedError

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return ctor("test:value-sugar", [])


@dataclass(frozen=True)
class _RefusingValue(FloorValue):
    refusal: SugarNotWritten

    def subscript(self, index, site):
        del index, site
        raise self.refusal


def _site(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "subscript_refusal.py"
    path.write_text("result = receiver[key]\n")
    tree = SourceFile.from_path(path.name)
    return next(node.fragment for node in tree.nodes() if isinstance(node, Subscript))


def test_partitioned_subscript_preserves_original_typed_refusal(tmp_path, monkeypatch):
    site = _site(tmp_path, monkeypatch)
    refusal = SugarNotWritten(
        blame=site,
        owner="RefusingValue.subscript",
        observed="authenticated undecided lookup",
        requested="producer testimony",
        fix="retain this typed refusal",
    )
    guard = atomic("test.receiver.completed", [])
    receiver = ExitSet(
        (
            Halted(
                complement_guard(guard),
                RaiseEffect(exception_name="RuntimeError", occurrence=str(site)),
            ),
            Completed(guard, _RefusingValue(refusal)),
        )
    )
    sugar = SubscriptSugar(
        _ValueSugar(receiver, site),
        _ValueSugar(Complete(StringValue("key")), site),
        site,
    )

    with pytest.raises(SugarNotWritten) as raised:
        sugar.desugar()

    assert raised.value is refusal


def test_partitioned_subscript_truth_keeps_value_and_halt_faces(tmp_path, monkeypatch):
    site = _site(tmp_path, monkeypatch)
    guard = atomic("test.receiver.completed", [])
    receiver = ExitSet(
        (
            Halted(
                complement_guard(guard),
                RaiseEffect(exception_name="RuntimeError", occurrence=str(site)),
            ),
            Completed(
                guard,
                DictValue(((StringValue("key"), TermValue(7)),)),
            ),
        )
    )
    sugar = SubscriptSugar(
        _ValueSugar(receiver, site),
        _ValueSugar(Complete(StringValue("key")), site),
        site,
    )

    exits = sugar.desugar()

    assert len(exits.exits) == 2
    assert any(isinstance(exit, Halted) for exit in exits.exits)
    completed = next(exit for exit in exits.exits if isinstance(exit, Completed))
    assert completed.value == TermValue(7)
