"""Every call binds and applies through one routine (#7757 entry 6, step 6).

A call has one form, however it is written: its actuals are bound by
``object_value.bind_call`` and its body is applied by
``CallSiteValue.producer_outcome``.  A plain call ``f()``, a method call
``self.m()``/``obj.m()``, a computed callee ``(lambda n: n)(4)``, ``f(**kw)``
and ``obj.m(**kw)`` all take that one road, so a body's raise reaches the
caller the same way from every form.

Before this change ``f(**kw)`` and ``(lambda ...)(...)`` each bound through
their own copy of the binder, and the computed call returned its body
unapplied: a lambda body's halts were never the call's.
"""

from __future__ import annotations

import pytest


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


def _routed(monkeypatch, source: str):
    """The test function's outcome, with every call the one binder bound and
    every call the one application applied."""
    from sugar_lift_py_tests.floor import object_value
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    bound: list = []
    applied: list = []
    real_bind = object_value.bind_call
    real_apply = CallSiteValue.producer_outcome

    def bind_spy(*args, **kwargs):
        callsite = real_bind(*args, **kwargs)
        bound.append(callsite)
        return callsite

    def apply_spy(self, *args, **kwargs):
        applied.append(self)
        return real_apply(self, *args, **kwargs)

    monkeypatch.setattr(object_value, "bind_call", bind_spy)
    monkeypatch.setattr(CallSiteValue, "producer_outcome", apply_spy)
    return _test_function_outcome(source), bound, applied


def _bound_and_applied(bound, applied, target_name: str) -> bool:
    return any(
        callsite.target_name == target_name
        and any(callsite is used for used in applied)
        for callsite in bound
    )


def _every_applied_body_was_bound_by_the_one_binder(bound, applied) -> bool:
    return all(
        any(callsite is made for made in bound)
        for callsite in applied
        if callsite.body is not None
    )


def _only_raise(outcome, exception: str) -> None:
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Halted], outcome
    assert outcome.exits[0].effect.exception_name == exception


# ---------------------------------------------------------------------------
# ``self.m()`` whose body raises carries the raise, exactly as ``f()`` does.
# ---------------------------------------------------------------------------

_PLAIN_CALL = """\
def check():
{body}


def run():
    state = check()
    return 3


def test_run():
    value = run()
    assert value == 3
"""

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

_RAISES = "    raise ValueError('bad')"
_COMPLETES = "    return None"


@pytest.mark.parametrize(
    ("form", "source", "target"),
    [
        ("plain", _PLAIN_CALL, "check"),
        ("self", _SELF_CALL, "Box.check"),
    ],
)
def test_a_raising_body_reaches_the_caller_from_a_plain_and_a_self_call(
    monkeypatch, form: str, source: str, target: str
) -> None:
    indent = "    " if form == "self" else ""
    completes = source.format(body=indent + _COMPLETES)
    raises = source.format(body=indent + _RAISES)

    assert _test_function_outcome(completes).completed_value() is not None
    outcome, bound, applied = _routed(monkeypatch, raises)
    _only_raise(outcome, "ValueError")
    assert _bound_and_applied(bound, applied, target)
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied)


# ---------------------------------------------------------------------------
# ``f(**kw)`` and ``obj.m(**kw)`` bind and apply through the same routine.
# ---------------------------------------------------------------------------

_SPREAD_FUNCTION_CALL = """\
def open_store(mode='r'):
{body}


def run(**kwargs):
    handle = open_store(**kwargs)
    return 1


def test_store():
    value = run(mode='r')
    assert value == 1
"""

_SPREAD_METHOD_CALL = """\
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


@pytest.mark.parametrize(
    ("form", "source", "target"),
    [
        ("f(**kw)", _SPREAD_FUNCTION_CALL, "open_store"),
        ("obj.m(**kw)", _SPREAD_METHOD_CALL, "Store.open"),
    ],
)
def test_spread_function_and_spread_method_calls_take_the_one_routine(
    monkeypatch, form: str, source: str, target: str
) -> None:
    indent = "    " if form == "obj.m(**kw)" else ""
    completes = source.format(body=indent + "    return mode")
    raises = source.format(body=indent + "    raise OSError('cannot open')")

    outcome, bound, applied = _routed(monkeypatch, completes)
    assert outcome.completed_value() is not None
    assert _bound_and_applied(bound, applied, target), form
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied), form

    outcome, bound, applied = _routed(monkeypatch, raises)
    _only_raise(outcome, "OSError")
    assert _bound_and_applied(bound, applied, target), form
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied), form


# ---------------------------------------------------------------------------
# A lambda called where it is written is the same call: bound, then applied.
# ---------------------------------------------------------------------------

_LAMBDA_CALL = """\
def test_lambda():
    value = (lambda n: n)(4)
    assert value == 4
"""


def test_an_inline_lambda_call_takes_the_one_routine(monkeypatch) -> None:
    outcome, bound, applied = _routed(monkeypatch, _LAMBDA_CALL)
    assert outcome.completed_value() is not None
    assert _bound_and_applied(bound, applied, "py.call")
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied)


# ---------------------------------------------------------------------------
# A lambda passed as a value and called there -- a callback, ``key=`` -- is the
# same call: bound, then applied, so its body's raise is the caller's.
# ---------------------------------------------------------------------------

_KEY_CALLBACK = """\
def fail(n):
    raise ValueError('bad')


def pick(items, key):
    chosen = key(items)
    return 3


def test_pick():
    value = pick(0, key=lambda n: {body})
    assert value == 3
"""


def test_a_key_lambda_whose_body_raises_carries_the_raise_to_the_caller(
    monkeypatch,
) -> None:
    outcome, bound, applied = _routed(monkeypatch, _KEY_CALLBACK.format(body="n"))
    assert outcome.completed_value() is not None
    assert _bound_and_applied(bound, applied, "py.call")
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied)

    outcome, bound, applied = _routed(monkeypatch, _KEY_CALLBACK.format(body="fail(n)"))
    _only_raise(outcome, "ValueError")
    assert _bound_and_applied(bound, applied, "py.call")
    assert _bound_and_applied(bound, applied, "fail")
    assert _every_applied_body_was_bound_by_the_one_binder(bound, applied)
