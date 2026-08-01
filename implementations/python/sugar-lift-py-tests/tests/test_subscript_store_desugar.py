from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import (
    BytesValue,
    ListValue,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.panic import SugarNotWritten


def _site(tmp_path):
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "store.py"
    path.write_text("def f(obj, key, value):\n    obj[key] = value\n")
    function = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    )
    return function.body[0].fragment


@dataclass(frozen=True)
class _ObservedSugar(Sugar):
    label: str
    value: object
    log: list[str]

    @classmethod
    def witnesses(cls):
        raise AssertionError("test helper has no witness")

    def desugar(self, ctx=None):
        del ctx
        self.log.append(self.label)
        return Complete(self.value)


def _store(receiver, key, value, log, site):
    return SubscriptStoreEffectSugar(
        receiver=_ObservedSugar("receiver", receiver, log),
        index=_ObservedSugar("key", key, log),
        value=_ObservedSugar("value", value, log),
        site=site,
    )


def test_subscript_store_evaluates_rhs_receiver_and_key_once_in_python_order(tmp_path):
    log: list[str] = []
    outcome = _store(
        ListValue((TermValue(1),)), TermValue(0), TermValue(7), log, _site(tmp_path)
    ).desugar()

    assert log == ["value", "receiver", "key"]
    assert outcome == Complete(ListValue((TermValue(7),)))


def test_readable_immutable_receiver_raises_on_store(tmp_path):
    receiver = TupleValue((TermValue(1),))
    assert receiver.subscript(TermValue(0), "read.py:1").value == TermValue(1)

    outcome = _store(
        receiver, TermValue(0), TermValue(7), [], _site(tmp_path)
    ).desugar()

    assert type(outcome).__name__ == "Incomplete"
    assert outcome.effect.exception_name == "TypeError"
    assert "TypeError" in repr(outcome.effect.exception_type_coordinate)
    assert "ValueError" not in repr(outcome.effect.exception_type_coordinate)
    assert outcome.effect.producer_node_owner == "TupleValue.setitem"


@pytest.mark.parametrize(
    ("receiver", "owner"),
    (
        (StringValue("abc"), "StringValue.setitem"),
        (BytesValue(b"abc"), "BytesValue.setitem"),
    ),
)
def test_immutable_slice_store_has_exact_typeerror_occurrence(
    tmp_path, receiver, owner
):
    site = _site(tmp_path)
    outcome = _store(
        receiver,
        SliceValue(TermValue(1), TermValue(2), None),
        ListValue((TermValue(9),)),
        [],
        site,
    ).desugar()

    assert type(outcome).__name__ == "Incomplete"
    assert outcome.effect.exception_name == "TypeError"
    assert outcome.effect.producer_node_owner == owner
    assert outcome.effect.occurrence_id == str(site)


@pytest.mark.parametrize(
    ("receiver", "fabricated"),
    (
        (StringValue("abc"), StringValue("a9c")),
        (BytesValue(b"abc"), BytesValue(b"a9c")),
    ),
)
def test_immutable_slice_store_cannot_fabricate_mutated_receiver(
    tmp_path, receiver, fabricated
):
    site = _site(tmp_path)
    outcome = _store(
        receiver,
        SliceValue(TermValue(1), TermValue(2), None),
        ListValue((TermValue(9),)),
        [],
        site,
    ).desugar()

    assert outcome != Complete(fabricated)
    assert outcome.effect.producer_node_owner != "TupleValue.setitem"


@pytest.mark.parametrize(
    "receiver", (StringValue("abc"), BytesValue(b"abc"))
)
def test_immutable_slice_store_halt_preserves_exact_prior_state(tmp_path, receiver):
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    prior = _ObservedSugar(
        "prior", BlockValue((TermValue(99),), can_fall_through=True), []
    )
    store = _store(
        receiver,
        SliceValue(TermValue(1), TermValue(2), None),
        ListValue((TermValue(9),)),
        [],
        _site(tmp_path),
    )

    outcome = reduce_block_to_exitset((prior, store), None)
    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert halted[0].state.entries == (TermValue(99),)


def test_undecided_store_never_claims_a_completed_face(tmp_path):
    store = _store(
        SymbolicValue(make_var("obj")),
        TermValue(0),
        TermValue(7),
        [],
        _site(tmp_path),
    )

    with pytest.raises(SugarNotWritten, match="undischarged subscript store"):
        store.desugar()


def test_rhs_halt_wins_before_receiver_or_key_evaluation(tmp_path):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.ir import str_const

    log: list[str] = []

    @dataclass(frozen=True)
    class _RaisingValue(Sugar):
        def desugar(self, ctx=None):
            del ctx
            log.append("value")
            return Complete(
                RaiseValue(
                    RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('store.py:4:12'), exception_type_coordinate=str_const('ValueError'))
                )
            )

        @classmethod
        def witnesses(cls):
            raise AssertionError

    store = SubscriptStoreEffectSugar(
        receiver=_ObservedSugar("receiver", ListValue(()), log),
        index=_ObservedSugar("key", TermValue(0), log),
        value=_RaisingValue(),
        site=_site(tmp_path),
    )
    outcome = store.desugar()

    assert log == ["value"]
    assert outcome.value.effect.exception_type_coordinate == str_const("ValueError")


def test_receiver_halt_wins_before_key_after_rhs_completed(tmp_path):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.ir import str_const

    log: list[str] = []

    @dataclass(frozen=True)
    class _RaisingReceiver(Sugar):
        def desugar(self, ctx=None):
            del ctx
            log.append("receiver")
            return Complete(
                RaiseValue(
                    RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('store.py:4:4'), exception_type_coordinate=str_const('LookupError'))
                )
            )

        @classmethod
        def witnesses(cls):
            raise AssertionError

    store = SubscriptStoreEffectSugar(
        receiver=_RaisingReceiver(),
        index=_ObservedSugar("key", TermValue(0), log),
        value=_ObservedSugar("value", TermValue(7), log),
        site=_site(tmp_path),
    )

    outcome = store.desugar()

    assert log == ["value", "receiver"]
    assert outcome.value.effect.exception_type_coordinate == str_const("LookupError")


def test_store_halt_preserves_state_completed_before_it(tmp_path):
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    prior = _ObservedSugar(
        "prior", BlockValue((TermValue(99),), can_fall_through=True), []
    )
    store = _store(
        TupleValue((TermValue(1),)),
        TermValue(0),
        TermValue(7),
        [],
        _site(tmp_path),
    )

    outcome = reduce_block_to_exitset((prior, store), None)

    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert TermValue(99) in halted[0].state.entries
