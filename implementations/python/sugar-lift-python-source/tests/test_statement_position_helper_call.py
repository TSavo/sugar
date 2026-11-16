"""A same-module helper called in statement position is its coordinate and edge.

``def g(x): return 1`` / ``def f(): g(2); return 0`` crashed the lift with
``BACKEND DEFECT [CallSiteValue.reduce_source_outcome] retained source
completion already seated``: the Call producer reduced ``g``'s body once
(publishing its halts at the Call) and seated the completion, and the
statement then reduced the body a second time to splice its field stores.

Neither reduction happens any more: a call of a same-file function is its
coordinate ``call:e.g(<args>)`` and its edge, joined to ``g``'s contract at
prove (#7757 steps 6 and 9; the body-following application is deleted,
#8705).  So the statement is reduced once, as the call: it completes with the
call's result, or halts with the one undetermined raise the edge owes.  What
``g``'s body raises is its contract's to state; the lift never names it at the
call, and never drops the call's halt.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, TermValue

from frame_fresh import fresh
from test_builtin_container_mutation import (
    _call_owners,
    _halt_names,
    _is_after_call,
    _returns,
)


@pytest.mark.parametrize(
    "helper, call",
    [
        ("def g(x):\n    return 1\n", "g(2)"),
        ("def g(x):\n    y = x\n", "g(2)"),
        ("def g(x):\n    x.append(1)\n", "g([])"),
        ("def g(x, y=3):\n    return x + y\n", "g(2)"),
    ],
)
def test_a_completing_helper_statement_completes(tmp_path, helper, call):
    source = helper + f"def f():\n    {call}\n    return 0\n"
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(0)]
    assert _call_owners(halts) == ["UnknownCallee:e.g"]


def test_a_raising_helper_statement_keeps_the_calls_halt(tmp_path):
    # ``g`` always raises, which its contract states: at prove the completed
    # face is refuted.  The lift keeps both faces of the one call and names
    # no ``ValueError`` read off the body.
    source = (
        "def g(x):\n    raise ValueError('x')\n"
        "def f():\n    g(2)\n    return 0\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(0)]
    assert _call_owners(halts) == ["UnknownCallee:e.g"]
    assert "ValueError" not in _halt_names(halts)


def test_a_helper_raise_reaches_the_handler(tmp_path):
    # The call's undetermined raise is tested by ``except ValueError``: caught
    # on one face, carried on as the call's halt on the other.
    source = (
        "def g(x):\n    raise ValueError('x')\n"
        "def f():\n    try:\n        g(2)\n    except ValueError:\n"
        "        return 'caught'\n    return 'no'\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert sorted(value.value for value in returns) == ["caught", "no"]
    assert _call_owners(halts) == ["UnknownCallee:e.g"]


def test_a_list_a_helper_may_mutate_is_never_its_pre_call_contents(tmp_path):
    source = (
        "def g(xs):\n    xs.append(1)\n"
        "def f():\n    r = []\n    g(r)\n    return r\n"
    )
    (value,), halts = _returns(tmp_path, source)
    assert _call_owners(halts) == ["UnknownCallee:e.g"]
    assert value != fresh(ListValue, ())
    assert _is_after_call(value, "xs", callee="e.g")
