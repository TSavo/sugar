"""CallSugar: a call is a coordinate into the vendor universe. Reduce the
arguments, and the result is the callsite -- a CallSiteValue whose term IS
`call:f(<args>)`. The lift does not derive f; the coordinate is the stated
address a dig lands on. The money test: `y = f(3); assert y == 7` states
InvValue(py.eq(call:f(3), 7)) -- the vendor-assert dig shape, the callsite
riding in the sentence itself."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    CallSiteValue,
    InvValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq, str_const


def test_call_reduces_to_its_coordinate() -> None:
    value = reduce_value("f(3)")
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:f", [num(3)])


def test_range_call_constructs_finite_elements_at_call_sugar_owner() -> None:
    value = reduce_value("range(1, 6, 2)")

    assert value == ListValue((TermValue(1), TermValue(3), TermValue(5)))


def test_large_range_call_is_a_typed_loud_finite_unfold_terminal() -> None:
    """#5361: over-cap decidable range is loud, never opaque Complete.

    numpy/lib/tests/test_loadtxt.py joins a generator over range(1, 110001);
    the prior unbounded range fold dominated reduce_body heartbeats.
    """
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT

    with pytest.raises(FactoryPanic) as panic:
        reduce_value(f"range(0, {STATIC_UNFOLD_LIMIT + 1})")

    assert panic.value.info.owner == "finite_unfold"
    assert panic.value.info.observed == f"range cardinality={STATIC_UNFOLD_LIMIT + 1}"


def test_enormous_range_length_overflow_is_a_typed_loud_terminal() -> None:
    with pytest.raises(FactoryPanic) as panic:
        reduce_value(f"range(0, {2**100})")

    assert panic.value.info.owner == "finite_unfold"
    assert panic.value.info.observed == "range cardinality exceeds sys.maxsize"


def test_over_cap_ground_tuple_repetition_stays_typed_loud() -> None:
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT

    with pytest.raises(FactoryPanic) as panic:
        reduce_value(f"(0,) * {STATIC_UNFOLD_LIMIT + 1}")

    assert panic.value.info.owner == "finite_unfold"


@pytest.mark.parametrize("sugar_name", ["list", "generator"])
def test_over_cap_finite_comprehensions_stay_typed_loud(sugar_name: str) -> None:
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT
    from sugar_lift_py_tests.sugar.generator_exp_sugar import GeneratorExpSugar
    from sugar_lift_py_tests.sugar.list_comp_sugar import ListCompSugar

    sugar_type = ListCompSugar if sugar_name == "list" else GeneratorExpSugar
    sugar = sugar_type(clauses=(), elt_body=None, site="over-cap finite test")
    iterable = ListValue((TermValue(0),) * (STATIC_UNFOLD_LIMIT + 1))

    with pytest.raises(FactoryPanic) as panic:
        sugar._finite_or_coordinate(iterable, None)

    assert panic.value.info.owner == "finite_unfold"


def test_over_cap_static_string_join_stays_typed_loud() -> None:
    from sugar_lift_py_tests.floor.string_value import _fold_string_method
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT

    operation = SimpleNamespace(
        name="join",
        arguments=(ArrayLiteral((StringValue("x"),) * (STATIC_UNFOLD_LIMIT + 1)),),
        blame="over-cap finite test",
    )

    with pytest.raises(FactoryPanic) as panic:
        _fold_string_method(StringValue(","), operation)

    assert panic.value.info.owner == "finite_unfold"


def test_range_at_static_unfold_limit_still_materializes() -> None:
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT

    value = reduce_value(f"range({STATIC_UNFOLD_LIMIT})")

    assert isinstance(value, ListValue)
    assert len(value.elements) == STATIC_UNFOLD_LIMIT


def test_symbolic_argument_rides_into_the_coordinate() -> None:
    value = reduce_value("f(z)", binds={"z": SymbolicValue(make_var("z"))})
    assert value.term == ctor("call:f", [make_var("z")])


def test_assert_on_a_call_result_states_the_dig_coordinate() -> None:
    # The loop closes: the assignment aliases y to f(3)'s source, the reference
    # recomposes it, equals emits over the callsite term, and the assert states
    # the inv -- py.eq(call:f(3), 7), the callsite IS in the sentence.
    block = compose_block("    y = f(3)\n    assert y == 7\n    return 1\n")
    inv = block.statements[0]
    assert isinstance(inv, InvValue)
    assert inv.formula == py_eq(ctor("call:f", [num(3)]), num(7))


def test_keyword_arguments_ride_the_coordinate() -> None:
    # Keyword VALUES are part of the call coordinate (not dropped). **kwargs
    # expansion stays a loud gap -- see test_call_kwargs_sugar.py.
    value = reduce_value("f(x=1)")
    assert isinstance(value, CallSiteValue)
    # The keyword NAME rides inside the term as a kw wrapper (richer than the
    # original names-in-parameters spelling): f(x=1) != f(y=1) at term level.
    assert value.term == ctor("call:f", [ctor("kw", [str_const("x"), num(1)])])
    assert value.parameters == ("x",)
