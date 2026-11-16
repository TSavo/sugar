"""A list handed to a same-file helper is the state the call leaves it in.

``def add(l): l.append(1)`` / ``r = []; add(r); return r``.  The lift once
followed the helper's body with each formal bound to the caller's actual and
read its stores back onto the caller's objects (``source_helper_actual_states``),
a second way of knowing what a callee does.  It is deleted (#8705): a call of
a same-file function is its coordinate ``call:e.add(<args>)`` and its edge,
joined to the helper's own contract at prove (#7757 steps 6 and 9).

The law now: whatever the helper's body is, the caller's object after the
call is ``python:after(<call result>, <formal>)``, the one spelling of an
object's state after a call, which the helper's contract states its post over.
It is never the pre-call contents and never a value the lift worked out from
the body.  The call keeps its halt (the edge is owed), and no exception the
body raises is named at the call.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, SymbolicValue

from frame_fresh import fresh
from test_builtin_container_mutation import (
    _call_owners,
    _halt_names,
    _ints,
    _is_after_call,
    _returns,
)


HELPERS = {
    "append": "def add(l):\n    l.append(1)\n",
    "append-operand": "def add(l, x=5):\n    l.append(x)\n    l.append(x)\n",
    "returns": "def add(l):\n    l.append(1)\n    return 7\n",
    "reads-only": "def add(l):\n    n = len(l)\n    return n\n",
    "loop": "def add(l):\n    for x in (1, 2):\n        l.append(x)\n",
    "rebinds": "def add(l):\n    l = [9]\n    l.append(1)\n",
    "recursive": "def add(l):\n    l.append(1)\n    add(l)\n",
    "unprojected": "import copy\ndef add(l):\n    copy.copy(l)\n",
    "raises": "def add(l):\n    l.pop()\n",
}


@pytest.mark.parametrize("call", ["add(r)", "y = add(r)"])
@pytest.mark.parametrize("helper", sorted(HELPERS))
def test_the_callers_list_is_the_calls_after_state(tmp_path, helper, call):
    source = HELPERS[helper] + f"def f():\n    r = []\n    {call}\n    return r\n"
    returns, halts = _returns(tmp_path, source)
    (value,) = returns
    assert _is_after_call(value, "l", callee="e.add")
    assert value != fresh(ListValue, ())
    # The call's own halt is kept, owed; the body's ``IndexError`` (``raises``)
    # is the helper's contract's to state, never named here.
    assert _call_owners(halts) == ["UnknownCallee:e.add"]
    assert "IndexError" not in _halt_names(halts)


def test_every_alias_sees_the_calls_after_state(tmp_path):
    source = HELPERS["append"] + (
        "def f():\n    r = []\n    a = r\n    add(r)\n    return a\n"
    )
    returns, _halts = _returns(tmp_path, source)
    (value,) = returns
    assert _is_after_call(value, "l", callee="e.add")


def test_a_later_store_in_the_caller_is_never_the_pre_call_list(tmp_path):
    source = HELPERS["append"] + (
        "def f():\n    r = []\n    add(r)\n    r.append(2)\n    return r\n"
    )
    # The append is on the object the call left, whose contents nothing here
    # decides: the list is unknown, never ``[2]`` built on the pre-call ``[]``
    # and never ``[1, 2]`` built on a body the lift followed.
    returns, _halts = _returns(tmp_path, source)
    assert returns
    for value in returns:
        assert type(value) is SymbolicValue


def test_a_name_that_only_contains_the_list_is_unknown(tmp_path):
    source = HELPERS["append"] + (
        "def f():\n    r = []\n    outer = [r]\n    add(r)\n    return outer\n"
    )
    # ``outer`` holds the object the call may change: never ``[[]]`` and never
    # ``[[1]]`` read off the helper's body.
    returns, _halts = _returns(tmp_path, source)
    assert returns
    for value in returns:
        assert value != fresh(ListValue, (fresh(ListValue, ()),))
        assert value != fresh(ListValue, (fresh(ListValue, _ints(1)),))
