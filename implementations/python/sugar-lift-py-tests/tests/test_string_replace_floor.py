from sugar_lift_py_tests.floor import StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete


def _call(receiver, name, *arguments):
    return receiver.call_named_method(
        name,
        arguments,
        owner="test",
        blame="enum.py:535:20",
    )


def test_exact_replace_then_split_constructs_the_returned_sequence() -> None:
    replaced = _call(
        StringValue("left,right third"),
        "replace",
        StringValue(","),
        StringValue(" "),
    )
    assert isinstance(replaced, Complete)
    assert replaced.value == StringValue("left right third")

    split = _call(replaced.value, "split")

    assert isinstance(split, Complete)
    assert tuple(item.value for item in split.value.items) == (
        "left",
        "right",
        "third",
    )


def test_replace_count_is_exact_and_not_ignored() -> None:
    outcome = _call(
        StringValue("a-a-a"),
        "replace",
        StringValue("a"),
        StringValue("b"),
        TermValue(2),
    )

    assert isinstance(outcome, Complete)
    assert outcome.value == StringValue("b-b-a")


def test_symbolic_replace_argument_cannot_mint_a_string_result() -> None:
    outcome = _call(
        StringValue("a-a"),
        "replace",
        SymbolicValue(make_var("old")),
        StringValue("b"),
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert not isinstance(outcome.value, StringValue)


def test_wrong_replace_arity_is_not_admitted() -> None:
    assert _call(StringValue("a"), "replace", StringValue("a")) is None
