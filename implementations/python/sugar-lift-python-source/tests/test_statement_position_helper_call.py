"""A same-module helper called in statement position consumes its one reduction.

``def g(x): return 1`` / ``def f(): g(2); return 0`` crashed the lift with
``BACKEND DEFECT [CallSiteValue.reduce_source_outcome] retained source
completion already seated``: the Call producer reduced ``g``'s body once
(publishing its halts at the Call) and seated the completion, and the
statement then reduced the body a second time to splice its field stores.

The law: a statement-position call whose body the producer already reduced
reads that retained completion; it never replays the producer. So the
helper's halts leave at the call exactly once, and its completed body is what
the statement splices.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, TermValue

from frame_fresh import fresh
from test_builtin_container_mutation import _halt_names, _returns


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
    assert halts == []


def test_a_raising_helper_statement_halts_once_at_the_call(tmp_path):
    source = (
        "def g(x):\n    raise ValueError('x')\n"
        "def f():\n    g(2)\n    return 0\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == []
    assert _halt_names(halts) == ["ValueError"]


def test_a_caught_helper_raise_reaches_the_handler(tmp_path):
    source = (
        "def g(x):\n    raise ValueError('x')\n"
        "def f():\n    try:\n        g(2)\n    except ValueError:\n"
        "        return 'caught'\n    return 'no'\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert [value.value for value in returns] == ["caught"]
    assert halts == []


def test_a_list_a_helper_may_mutate_is_never_its_pre_call_contents(tmp_path):
    source = (
        "def g(xs):\n    xs.append(1)\n"
        "def f():\n    r = []\n    g(r)\n    return r\n"
    )
    (value,), halts = _returns(tmp_path, source)
    assert halts == []
    assert value != fresh(ListValue, ())
