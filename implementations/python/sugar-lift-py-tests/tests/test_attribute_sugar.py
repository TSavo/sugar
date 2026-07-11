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
    value = reduce_value(
        "arr.shape", binds={"arr": SymbolicValue(make_var("arr"))}
    )
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:shape", [make_var("arr")])
    assert value.target_name == "shape"


def test_nested_attribute_is_nested_coordinate() -> None:
    # a.b.c -> call:c(call:b(a)), not py.attr.
    value = reduce_value(
        "arr.shape.dtype", binds={"arr": SymbolicValue(make_var("arr"))}
    )
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "call:dtype", [ctor("call:shape", [make_var("arr")])]
    )


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
    # AttributeSugar owns the Attribute, but its receiver is still audited.
    # ListComp has no sugar -- construction panics before desugar.
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("[x for x in y].shape")
    assert raised.value.info.observed == "ListComp"


def test_method_call_is_not_owned_by_attribute_sugar() -> None:
    # CallSugar/OsSugar own Call nodes. AttributeSugar owns Attribute terms.
    # `x.m()` is a Call whose func is an Attribute -- the Call is still unowned
    # (method-call sugar is a different arm); the func Attribute is never built
    # as a TERM by the call path, so the shapes stay disjoint.
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("x.m()", binds={"x": SymbolicValue(make_var("x"))})
    assert raised.value.info.observed == "Call"
