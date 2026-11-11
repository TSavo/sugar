"""A method call applies its body through the one application routine (#7756).

A plain call ``f(...)`` runs ``f``'s body through ``CallSiteValue.producer_outcome``
and carries every face of it: completions and raises.  A bound method call
``obj.m(...)`` is the same application with the receiver bound as the first
actual (``object_value.apply_bound_method``), so a method that raises leaves its
caller raising.

Each pair differs in exactly one thing and goes through the real solver:
the truthful source's claim holds (``sat``); the lying source makes the method
raise, so the assertion after the call is never reached (``unsat``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def bound_method_call_at(call_node, ctx=None):
    """The method call at ``call_node`` as bound, before it is applied.

    ``receiver.m(args)`` desugars to ``m(receiver, args)`` bound by the
    receiver's ``bound_method_call`` and applied once by
    ``CallSiteValue.producer_outcome``.  Unit tests that inspect the binding
    (the receiver in slot 0, the actuals in formal order) read it here; the
    Call itself yields the applied outcome.
    """
    sugar = call_node.sugar()

    def operand(item):
        return item.desugar(ctx).value.project_operation_receiver(
            ctx, owner="bound_method_call_at"
        )

    return operand(sugar.receiver).bound_method_call(
        sugar.name,
        tuple(operand(argument) for argument in sugar.args),
        owner="bound_method_call_at",
        blame=sugar.site,
        ctx=ctx,
        keywords=tuple((name, operand(value)) for name, value in sugar.keywords),
        required_frame=sugar.source_call_frame,
    )


def _pair(tmp_path: Path, name: str, truthful: str, lying: str) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict == "sat"
    assert lie.verdict == "unsat"


_OBJ_CALL = """\
class Gauge:
    def __init__(self, n):
        self.n = n

    def read(self):
{body}


def test_gauge():
    gauge = Gauge(4)
    value = gauge.read()
    assert value == 4
"""


def test_receiver_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``obj.m()``: ``m`` completes vs ``m`` always raises."""

    _pair(
        tmp_path,
        "obj-call",
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
    )


_SELF_CALL = """\
class Box:
    def __init__(self, n):
        self.n = n

    def run(self):
        state = self.check()
        return self.n

    def check(self):
{body}


def test_box():
    box = Box(3)
    value = box.run()
    assert value == 3
"""


def test_self_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``self.m()`` inside a method: ``m`` completes vs ``m`` always raises."""

    _pair(
        tmp_path,
        "self-call",
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
    )


_ONE_BRANCH = """\
class Limit:
    def __init__(self, n):
        self.n = n

    def run(self, n):
        state = self.check(n=n)
        return state

    def check(self, n):
        if n > 5:
            raise ValueError('too big')
        return n


def test_limit():
    limit = Limit(0)
    value = limit.run({actual})
    assert value == {actual}
"""


def test_method_raising_on_one_branch_carries_that_raise(tmp_path: Path) -> None:
    """``self.m(n=n)`` raising on one branch: the actual selects the arm."""

    _pair(
        tmp_path,
        "one-branch",
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
    )


_SUPER_CALL = """\
class Base:
    def check(self):
{body}


class Child(Base):
    def __init__(self, n):
        self.n = n

    def run(self):
        state = super().check()
        return self.n


def test_child():
    child = Child(2)
    value = child.run()
    assert value == 2
"""


def test_super_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``super().m()``: the base method completes vs always raises."""

    _pair(
        tmp_path,
        "super-call",
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
    )


_SPREAD_CALL = """\
class Store:
    def __init__(self):
        self.mode = 'r'

    def run(self, **kwargs):
        handle = self.open(**kwargs)
        return 1

    def open(self, mode='r'):
{body}


def test_store():
    store = Store()
    value = store.run(mode='r')
    assert value == 1
"""


def test_spread_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``self.m(**kwargs)``: the method completes vs always raises."""

    _pair(
        tmp_path,
        "spread-call",
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
    )


# ---------------------------------------------------------------------------
# The same pairs in process (a unit check, not a twin): the lifter's own
# outcome for the test function.  Truthful completes; lying carries only the
# method's raise.  Before #7756 every lying source here completed.
# ---------------------------------------------------------------------------


_IN_PROCESS_PAIRS = {
    "obj-call": (
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
        "KeyError",
    ),
    "self-call": (
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
        "ValueError",
    ),
    "one-branch": (
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
        "ValueError",
    ),
    "super-call": (
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
        "ValueError",
    ),
    "spread-call": (
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
        "OSError",
    ),
}


def _test_function_outcome(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


@pytest.mark.parametrize("form", sorted(_IN_PROCESS_PAIRS))
def test_method_raise_reaches_the_caller_in_process(form: str) -> None:
    from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted

    truthful, lying, exception = _IN_PROCESS_PAIRS[form]
    assert isinstance(_test_function_outcome(truthful), Complete)
    outcome = _test_function_outcome(lying)
    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Halted]
    assert outcome.exits[0].effect.exception_name == exception
