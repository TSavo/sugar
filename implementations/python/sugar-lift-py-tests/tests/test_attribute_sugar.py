"""AttributeSugar: `x.attr` is a unary coordinate call:<attr>(receiver).

Same head family as methods (and CallSugar's opaque-coordinate doctrine) --
NOT py.attr(receiver, name). The LAW lives in symbolic_term's Attribute case;
this sugar is the factory arm that owns the Attribute TERM and projects it.
"""

from __future__ import annotations

import pytest

from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, InvValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq


def test_attribute_reduces_to_call_attr_coordinate() -> None:
    value = reduce_value("arr.shape", binds={"arr": SymbolicValue(make_var("arr"))})
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:shape", [make_var("arr")])
    assert value.target_name == "shape"


def test_nested_attribute_is_nested_coordinate() -> None:
    # a.b.c -> call:c(call:b(a)), not py.attr.
    value = reduce_value(
        "arr.shape.dtype", binds={"arr": SymbolicValue(make_var("arr"))}
    )
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:dtype", [ctor("call:shape", [make_var("arr")])])


def test_assert_on_an_attribute_states_the_dig_coordinate() -> None:
    # Assignment aliases y to x.shape's source; equals emits over the
    # coordinate term; the assert states InvValue(py.eq(call:shape(x), 7)).
    block = compose_block(
        "    y = x.shape\n    assert y == 7\n    return 1\n",
        binds={"x": SymbolicValue(make_var("x"))},
    )
    inv = block.statements[0]
    assert isinstance(inv, InvValue)
    assert inv.formula == py_eq(ctor("call:shape", [make_var("x")]), num(7))


def test_unowned_receiver_panics_at_construction() -> None:
    # AttributeSugar owns the Attribute; the receiver is still audited/reduced.
    # Free name `y` inside a comprehension receiver must panic loud (never
    # invent). ListComp may itself be owned on current floors — the instrument
    # pins refuse-loud on the unresolved free name, not a soft green.
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("[x for x in y].shape")
    assert raised.value.info.observed in ("ListComp", "y")


def test_method_call_is_not_owned_by_attribute_sugar() -> None:
    # AttributeSugar owns Attribute terms only. MethodCallSugar owns the Call
    # node of `x.m()` -- the func Attribute is never built as a TERM by that
    # path, so the shapes stay disjoint. Bare attribute still uses AttributeSugar.
    bare = reduce_value("x.m", binds={"x": SymbolicValue(make_var("x"))})
    called = reduce_value("x.m()", binds={"x": SymbolicValue(make_var("x"))})
    assert bare.term == ctor("call:m", [make_var("x")])
    assert called.term == ctor("call:m", [make_var("x")])
    # Same coordinate head family; the Call path is MethodCallSugar's.
    assert bare.target_name == called.target_name == "m"
