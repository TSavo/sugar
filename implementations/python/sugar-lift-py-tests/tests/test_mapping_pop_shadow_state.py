"""Receiver-owned shadow state read by a ``dict`` subclass's inherited
``get`` and ``items``.

The inherited ``dict.pop`` this file also pinned is deleted (#7757 H3):
``self.pop(k, d)`` is the dispatched member, decided at prove
(``test_dict_subclass_pop_dispatched_twins_7757``).
"""

from sugar_lift_py_tests.floor import (
    MappingObjectValue,
    StringValue,
    TermValue,
    TupleValue,
)

from frame_fresh import FRAME_FRESH


def test_inherited_get_projects_present_and_default_values() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        allocation=FRAME_FRESH,
        entries=((StringValue("present"), TermValue(1)),),
    )

    present = receiver.call_method_value(
        "get", (StringValue("present"), TermValue(9)), owner="test", blame="site"
    )
    missing = receiver.call_method_value(
        "get", (StringValue("missing"), TermValue(9)), owner="test", blame="site"
    )

    assert present.completed_value() == TermValue(1)
    assert missing.completed_value() == TermValue(9)


def test_inherited_items_retains_insertion_order_and_pairing() -> None:
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        allocation=FRAME_FRESH,
        entries=(
            (StringValue("first"), TermValue(1)),
            (StringValue("second"), TermValue(2)),
        ),
    )

    outcome = receiver.call_method_value("items", (), owner="test", blame="site")

    assert outcome.completed_value() is not None
    assert outcome.completed_value() == TupleValue(
        (
            TupleValue((StringValue("first"), TermValue(1))),
            TupleValue((StringValue("second"), TermValue(2))),
        )
    )
