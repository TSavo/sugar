from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.effect import (
    SequenceRepetitionRuntimeEffect,
    SubscriptStoreRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    ImportAliasValue,
    OpaqueOpCallsite,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome import Incomplete

_SITE = SourceFragment.from_source("xs * n\n", "runtime_repeat.py").statements()[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("[1, 2] * 3", (1, 2, 1, 2, 1, 2)),
        ("3 * [1, 2]", (1, 2, 1, 2, 1, 2)),
        ("[1, 2] * 0", ()),
        ("0 * [1, 2]", ()),
        ("[1, 2] * -2", ()),
        ("-2 * [1, 2]", ()),
    ),
)
def test_list_repetition_constructs_exact_python_order_through_multiply_sugar(
    source: str, expected: tuple[int, ...]
) -> None:
    value = reduce_value(source)

    assert value == ListValue(tuple(TermValue(item) for item in expected))


@pytest.mark.parametrize("source", ("[first, second] * 2", "2 * [first, second]"))
def test_list_repetition_preserves_reduced_element_identities(source: str) -> None:
    first = SymbolicValue(make_var("first_value"))
    second = SymbolicValue(make_var("second_value"))

    value = reduce_value(source, {"first": first, "second": second})

    assert type(value) is ListValue
    assert value.elements == (first, second, first, second)
    assert value.elements[0] is value.elements[2] is first
    assert value.elements[1] is value.elements[3] is second


@pytest.mark.parametrize("count", (3, 0, -2))
def test_string_multiply_matches_python(count: int) -> None:
    expected = "ab" * count

    value = reduce_value(f"'ab' * {count}")

    assert value == StringValue(expected)


@pytest.mark.parametrize("left,right", ((3, 4), (2, 1.5), (-2, 3)))
def test_number_multiply_matches_python(left: int | float, right: int | float) -> None:
    expected = left * right

    value = reduce_value(f"{left!r} * {right!r}")

    assert value == TermValue(expected)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "'ab' * count",
            ctor("*", [StringValue("ab").to_term(owner="test"), make_var("count")]),
        ),
        ("2 * count", ctor("*", [num(2), make_var("count")])),
    ),
)
def test_non_list_symbolic_multiplier_uses_native_operator_coordinate(
    source, expected
) -> None:
    value = reduce_value(source, {"count": SymbolicValue(make_var("count"))})

    assert value == SymbolicValue(expected)


def test_imported_list_repetition_count_remains_a_named_loud_gap() -> None:
    count = ImportAliasValue("start_caching_at", "start_caching_at")
    receiver = ListValue((StringValue("2024-01-01"),))

    with pytest.raises(
        FactoryPanic,
        match="ListValue.*stand on the multiplication floor",
    ):
        receiver.multiply(count, "test_to_datetime.py:3626:17")


@pytest.mark.parametrize("reversed_operands", (False, True))
def test_runtime_list_repetition_count_is_a_named_typed_effect(
    reversed_operands: bool,
) -> None:
    count = SymbolicValue(make_var("runtime_n"))
    items = ListValue((TermValue(7),))

    outcome = (
        count.multiply(items, _SITE)
        if reversed_operands
        else items.multiply(count, _SITE)
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "ListValue depends on runtime __index__/length semantics" in outcome.reason
    assert outcome.effect.witness.operand == make_var("runtime_n")
    assert outcome.effect.witness.operation == ctor(
        "py.sequence_repeat", [make_var("runtime_n")]
    )


def test_len_result_is_a_warranted_runtime_list_repetition_count() -> None:
    count = OpaqueOpCallsite(
        callee="len",
        arg=SymbolicValue(make_var("runtime_items")),
        computed=None,
    )

    outcome = ListValue((TermValue(7),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted len(...) result" in outcome.reason
    assert outcome.effect.witness.operand == ctor(
        "call:len", [make_var("runtime_items")], symbol_kind="method-coordinate"
    )


def test_opaque_non_index_result_remains_a_loud_list_repetition_gap() -> None:
    count = OpaqueOpCallsite(
        callee="str",
        arg=SymbolicValue(make_var("runtime_value")),
        computed=None,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(7),)).multiply(count, _SITE)


@pytest.mark.parametrize(
    "count",
    (
        CallSiteValue(
            target_name="ndim",
            arg_values=(SymbolicValue(make_var("array")),),
            parameters=(),
            term=ctor("call:ndim", [make_var("array")]),
            body=None,
            site=_SITE,
        ),
        CallSiteValue(
            target_name="max",
            arg_values=(TermValue(0), SymbolicValue(make_var("runtime_n"))),
            parameters=(),
            term=ctor("call:max", [num(0), make_var("runtime_n")]),
            body=None,
            site=_SITE,
        ),
    ),
)
def test_integer_warranted_callsite_is_a_runtime_list_repetition_count(
    count: CallSiteValue,
) -> None:
    outcome = ListValue((TermValue(7),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted callsite" in outcome.reason
    assert outcome.effect.witness.operand == count.term


def test_unwarranted_callsite_remains_a_loud_list_repetition_gap() -> None:
    count = CallSiteValue(
        target_name="make_count",
        arg_values=(SymbolicValue(make_var("value")),),
        parameters=(),
        term=ctor("call:make_count", [make_var("value")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(7),)).multiply(count, _SITE)


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (ListValue((TermValue(1),)), ListValue((TermValue(2),))),
        (StringValue("a"), StringValue("b")),
    ),
)
def test_ground_invalid_multiplication_stays_loud(left, right) -> None:
    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        left.multiply(right, "t.py:1:0")


@pytest.mark.parametrize(
    "source",
    (
        "[1] * [2]",
        "[1] * 2.0",
        "2.0 * [1]",
        "[1] * True",
        "True * [1]",
    ),
)
def test_non_index_list_repetition_operands_remain_named_loud_gaps(source: str) -> None:
    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        reduce_value(source)


def test_ranked_receivers_declare_multiply_arms() -> None:
    assert "multiply" in ListValue.__dict__
    assert "multiply" in TermValue.__dict__
    assert "multiply" in StringValue.__dict__
    assert "multiply" in SymbolicValue.__dict__


def test_unprojectable_multiplier_remains_a_loud_floor_gap() -> None:
    class Unprojectable(ListValue):
        pass

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(1),)).multiply(Unprojectable(()), "t.py:1:0")


def test_guarded_descendant_preserves_the_typed_store_effect() -> None:
    effect = Incomplete(
        SubscriptStoreRuntimeEffect(
            "symbolic store",
            **runtime_effect_evidence(
                "py.setitem",
                make_var("runtime_index"),
                SourceFragment.from_source("x[i] = 1\n", "t.py").statements()[0],
            ),
        )
    )
    guard = atomic("guard", [])

    guarded = effect.guarded(guard)

    assert isinstance(guarded, Incomplete)
    assert isinstance(guarded.effect, SubscriptStoreRuntimeEffect)
    assert "symbolic store" in guarded.reason
    assert "under branch condition" in guarded.reason
    assert "guard" in guarded.reason
