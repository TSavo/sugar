from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    ListValue,
    ImportAliasValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome import Incomplete


@pytest.mark.parametrize("count", (3, 0, -2))
def test_list_multiply_matches_python(count: int) -> None:
    expected = [1, 2] * count

    value = reduce_value(f"[1, 2] * {count}")

    assert value == ListValue(tuple(TermValue(item) for item in expected))


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
        ("[1, 2] * count", ctor("*", [ctor("array", [num(1), num(2)]), make_var("count")])),
        ("'ab' * count", ctor("*", [StringValue("ab").to_term(owner="test"), make_var("count")])),
        ("2 * count", ctor("*", [num(2), make_var("count")])),
    ),
)
def test_symbolic_multiplier_uses_native_operator_coordinate(source, expected) -> None:
    value = reduce_value(source, {"count": SymbolicValue(make_var("count"))})

    assert value == SymbolicValue(expected)


def test_imported_count_uses_native_operator_coordinate() -> None:
    count = ImportAliasValue("start_caching_at", "start_caching_at")
    receiver = ListValue((StringValue("2024-01-01"),))

    outcome = receiver.multiply(count, "test_to_datetime.py:3626:17")

    assert outcome.value == SymbolicValue(
        ctor(
            "*",
            [
                receiver.to_term(owner="test"),
                count.to_term(owner="test"),
            ],
        )
    )


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
    effect = Incomplete(SubscriptStoreRuntimeEffect("symbolic store"))
    guard = atomic("guard", [])

    guarded = effect.guarded(guard)

    assert isinstance(guarded, Incomplete)
    assert isinstance(guarded.effect, SubscriptStoreRuntimeEffect)
    assert "symbolic store" in guarded.reason
    assert "under branch condition" in guarded.reason
    assert "guard" in guarded.reason
