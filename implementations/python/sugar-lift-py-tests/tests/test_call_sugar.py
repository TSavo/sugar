"""CallSugar: a call is a coordinate into the vendor universe. Reduce the
arguments, and the result is the callsite -- a CallSiteValue whose term IS
`call:f(<args>)`. The lift does not derive f; the coordinate is the stated
address a dig lands on. The money test: `y = f(3); assert y == 7` states
InvValue(py.eq(call:f(3), 7)) -- the vendor-assert dig shape, the callsite
riding in the sentence itself."""

from __future__ import annotations

import pytest

from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.floor import CallSiteValue, InvValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq, str_const


def test_call_reduces_to_its_coordinate() -> None:
    value = reduce_value("f(3)")
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:f", [num(3)])


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
