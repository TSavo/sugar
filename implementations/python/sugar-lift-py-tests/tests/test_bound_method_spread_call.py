"""``self.m(**kwargs)``: a source method read off its receiver is a bound method.

Python evaluates ``receiver.m`` for an ordinary function ``m`` on the receiver's
class as a bound method, and calling it runs ``type(receiver).m(receiver, ...)``.
A call with ``*``/``**`` reads its callee as a value first, so the lifter yields
a ``BoundMethodValue`` for that read and the spread call dispatches through the
receiver's own ``call_method_value`` (the selection ``MethodCallSugar`` uses).
A ``staticmethod`` read off the instance binds differently and still refuses
by name.
"""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _returned(source: str):
    tree = SourceFile(
        (source, "bound_method.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    outcome = function_universe_outcome(function)
    assert isinstance(outcome, Complete)
    (statement,) = outcome.value.record.statements
    return statement.value


_BOX = (
    "class Box:\n"
    "    def __init__(self, **kwargs):\n"
    "        self.n = self.pick(**kwargs)\n"
    "    {decorator}def pick({receiver}n, m=10):\n"
    "        return {body}\n"
    "def f():\n"
    "    return Box(n=3).n\n"
)


def _box(body: str, *, decorator: str = "", receiver: str = "self, ") -> str:
    return _BOX.format(decorator=decorator, receiver=receiver, body=body)


def _method_result(source: str):
    """The stored field is the method call; its body's return is the value."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    call = _returned(source)
    assert isinstance(call, CallSiteValue)
    assert call.target_name == "Box.pick"
    outcome = call.retained_source_completion_outcome()
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, BlockValue)
    (returned,) = outcome.value.statements
    assert isinstance(returned, ReturnValue)
    return returned.value


def _native(source: str):
    namespace: dict = {}
    exec(source, namespace)
    return namespace["f"]()


def test_spread_call_on_self_runs_the_class_method_body():
    source = _box("n + m")
    assert _native(source) == 13

    value = _method_result(source)
    assert isinstance(value, TermValue)
    assert value.value == 13


def test_spread_call_on_self_yields_that_body_not_another():
    # Lying twin: the same call shape with a different method body decides a
    # different value; the lift follows the body, never a guess.
    source = _box("n - m")
    assert _native(source) == -7

    value = _method_result(source)
    assert isinstance(value, TermValue)
    assert value.value != 13
    assert value.value == -7


def test_a_staticmethod_read_off_the_instance_still_refuses_by_name():
    source = _box("n", decorator="@staticmethod\n    ", receiver="")
    assert _native(source) == 3

    with pytest.raises(ConstructionPanic, match="ObjectValue.attribute"):
        _returned(source)
