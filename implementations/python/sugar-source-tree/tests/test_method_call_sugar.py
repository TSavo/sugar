"""The attribute callee: `<receiver>.<name>(<args>)` -- the census's largest
family (61%). A composition: receiver reduces like any value; the call stands as
the method coordinate `call:<name>(receiver, args)`; chains compose; the
receiver rides as runtime_dispatch_receiver for a future type-aware dig."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import (
    completed_function_value,
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
    # Deleted expectation: the formal equality completed with an actual the
    # test supplied for s. It waits as ``equals`` over the method coordinate.
    carrier = native_carrier_for(
        _fn("def A(s):\n    assert s.upper() == s\n    return s\n"),
        operator="equals",
    )
    left, right = carrier.operands
    assert left.to_term(owner="method equality carrier tooth").name == "call:upper"
    assert right.to_term(owner="method equality carrier tooth").name == "s"


def test_keyword_args_lift():
    t = _out("def A(z):\n    return z.get(1, default=2)\n")
    assert t.name == "call:get"
    kwarg = t.args[-1]
    assert kwarg.name == "py.kwarg"
    assert kwarg.args[0].value == "default"


def _attribute_operations(node, found, depth=0):
    """Every ``python:attribute_result("<name>", <receiver>, <key>)`` in
    ``node`` -- a parameter's read, keyed per evaluation
    (``floor_value.undecided_attribute_result``): ``(receiver name,
    attribute name)``."""
    if depth > 64:
        return found
    if getattr(node, "name", None) == "python:attribute_result":
        found.append((getattr(node.args[1], "name", None), node.args[0].value))
    for child in (
        *(getattr(node, "args", ()) or ()),
        *(getattr(node, "operands", ()) or ()),
    ):
        _attribute_operations(child, found, depth + 1)
    return found


def test_spread_keyword_args_build_reference_method_call():
    """Expected shape changed (#7757 audit 2 row NEW-1): the callee read
    ``z.get`` on the formal ``z`` was an ``attribute_named`` carrier waiting
    on a caller's actual.  It is the one two-faced undecided read
    (``SymbolicValue.attribute``): its halt, naming ``z`` and ``get``, is
    kept, and nothing completes with one value.  Whatever the call with
    ``**d`` still defers (another family's operation) is discharged with no
    actual, every arm beside it kept (#7825)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome import ExitSet

    outcome = _fn("def A(z, d):\n    return z.get(1, **d)\n").sugar().desugar()
    assert getattr(getattr(outcome, "demand", None), "operator", None) != (
        "attribute_named"
    )
    if isinstance(outcome, NativeOperationExitCarrierV1):
        outcome = outcome.discharge(None, {})
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.completed_value() is None
    (halt,) = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "SymbolicValue.attribute"
    ]
    assert _attribute_operations(halt.guard, []) == [("z", "get")]


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
