"""Receiver-owned shadow state for inherited ``dict.pop``."""

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import (
    MappingObjectValue,
    ObjectField,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.mapping_pop_state_sugar import MappingPopStateSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    value: object
    evaluations: list[str] = field(compare=False)
    label: str
    site: object = field(default="test", compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.evaluations.append(self.label)
        return Complete(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def _pop(receiver, key):
    order = []
    outcome = MappingPopStateSugar(
        receiver=_FloorSugar(receiver, order, "receiver"),
        key=_FloorSugar(key, order, "key"),
        default=_FloorSugar(TermValue(None), order, "default"),
        site="pop-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert order == ["receiver", "key", "default"]
    return outcome.value


def test_present_key_is_removed_without_replacing_receiver_identity() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (ObjectField("source_field", TermValue(7)),),
        identity="receiver-coordinate",
        entries=(
            (StringValue("remove"), TermValue(1)),
            (StringValue("keep"), TermValue(2)),
        ),
    )

    updated = _pop(receiver, StringValue("remove"))

    assert isinstance(updated, MappingObjectValue)
    assert updated.identity == receiver.identity
    assert updated.fields == receiver.fields
    assert updated.entries == ((StringValue("keep"), TermValue(2)),)


def test_absent_key_with_default_preserves_exact_receiver() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        entries=((StringValue("keep"), TermValue(2)),),
    )

    assert _pop(receiver, StringValue("missing")) is receiver


def test_same_spelling_wrong_key_does_not_remove_an_entry() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        entries=((StringValue("remove"), TermValue(1)),),
    )

    updated = _pop(receiver, StringValue("other"))

    assert updated.entries == receiver.entries


def test_inherited_get_projects_present_and_default_values() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        entries=((StringValue("present"), TermValue(1)),),
    )

    present = receiver.call_method_value(
        "get", (StringValue("present"), TermValue(9)), owner="test", blame="site"
    )
    missing = receiver.call_method_value(
        "get", (StringValue("missing"), TermValue(9)), owner="test", blame="site"
    )

    assert isinstance(present, Complete) and present.value == TermValue(1)
    assert isinstance(missing, Complete) and missing.value == TermValue(9)


def test_inherited_items_retains_insertion_order_and_pairing() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        entries=(
            (StringValue("first"), TermValue(1)),
            (StringValue("second"), TermValue(2)),
        ),
    )

    outcome = receiver.call_method_value("items", (), owner="test", blame="site")

    assert isinstance(outcome, Complete)
    assert outcome.value == TupleValue(
        (
            TupleValue((StringValue("first"), TermValue(1))),
            TupleValue((StringValue("second"), TermValue(2))),
        )
    )
