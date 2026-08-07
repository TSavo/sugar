"""The attribute callee: `<receiver>.<name>(<args>)` -- the census's largest
family (61%). A composition: receiver reduces like any value; the call stands as
the method coordinate `call:<name>(receiver, args)`; chains compose; the
receiver rides as runtime_dispatch_receiver for a future type-aware dig."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import (
    authenticated_function_value,
    completed_function_value,
    native_carrier_for,
)


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _out(src):
    return completed_function_value(_fn(src)).post().args[1]


def test_method_call_is_the_method_coordinate():
    t = _out("def A(z):\n    return z.bit_length()\n")
    assert t.name == "call:bit_length"
    assert t.args[0].name == "z"  # the receiver is the first coordinate operand


def test_method_chains_compose():
    # z.get(k).strip() -> call:strip(call:get(z, k))
    t = _out("def A(z, k):\n    return z.get(k).strip()\n")
    assert t.name == "call:strip"
    inner = t.args[0]
    assert inner.name == "call:get"
    assert inner.args[0].name == "z" and inner.args[1].name == "k"


def test_assert_consumes_the_coordinate():
    # Deleted expectation: the formal equality completed before its caller bound s.
    inv = authenticated_function_value(
        _fn("def A(s):\n    assert s.upper() == s\n    return s\n"),
        operator="equals",
    ).invs()[0]
    assert inv.name == "py.eq"
    assert inv.args[0].name == "call:upper"


def test_keyword_args_lift():
    t = _out("def A(z):\n    return z.get(1, default=2)\n")
    assert t.name == "call:get"
    kwarg = t.args[-1]
    assert kwarg.name == "py.kwarg"
    assert kwarg.args[0].value == "default"


def test_spread_keyword_args_build_reference_method_call():
    """Deleted expectation: formal attribute lookup completed before binding z."""
    carrier = native_carrier_for(
        _fn("def A(z, d):\n    return z.get(1, **d)\n"),
        operator="attribute_named",
    )
    receiver, name = carrier.operands
    assert receiver.to_term(owner="method receiver carrier tooth").name == "z"
    assert name.value == "get"
    assert len(carrier.continuations) == 5


def test_spread_call_is_a_constructed_method_argument_coordinate():
    t = _out(
        "def A(cls, values):\n"
        "    value = str(*values)\n"
        "    return str.__new__(cls, value)\n"
    )

    assert t.name == "call:__new__"
    spread = t.args[2]
    assert spread.name == "python:call"
    assert spread.args[0].value == "str"
    assert spread.args[1].name == "python:starred_arg"
    assert spread.args[1].args[0].name == "values"


if __name__ == "__main__":
    test_method_call_is_the_method_coordinate()
    test_method_chains_compose()
    test_assert_consumes_the_coordinate()
    test_keyword_args_stay_loud()
    print("ok: method calls -- coordinate, chains, assert; kwargs/computed loud")
