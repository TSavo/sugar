"""MessageOpaqueValue propagates opaquely on the surfaces the failure-message
path exercises, instead of refusing like SymbolicValue does."""

from __future__ import annotations

from sugar_lift_py_tests.floor.message_opaque_value import MessageOpaqueValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete


def _opaque() -> MessageOpaqueValue:
    return MessageOpaqueValue(
        term=ctor("python:message-opaque-value", [str_const("x.y")], symbol_kind="coordinate")
    )


def test_is_a_symbolic_value_so_arithmetic_string_machinery_applies() -> None:
    assert isinstance(_opaque(), SymbolicValue)


def test_attribute_yields_message_opacity() -> None:
    out = _opaque().attribute("get_verbosity", site="s")
    assert isinstance(out, Complete)
    assert isinstance(out.value, MessageOpaqueValue)


def test_subscript_yields_message_opacity() -> None:
    out = _opaque().subscript(0, site="s")
    assert isinstance(out, Complete)
    assert isinstance(out.value, MessageOpaqueValue)


def test_contains_yields_message_opacity() -> None:
    out = _opaque().contains(_opaque(), site="s")
    assert isinstance(out, Complete)
    assert isinstance(out.value, MessageOpaqueValue)
