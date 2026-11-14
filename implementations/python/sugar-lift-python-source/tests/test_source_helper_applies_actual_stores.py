"""A call to a lifted source helper applies its body's stores to the actuals.

``def add(l): l.append(1)`` / ``r = []; add(r); return r`` lifted as an unknown
``python:receiver_after_call``: the caller havocked every decided container it
passed to a source call, even though the helper's body is right there and says
what it does. ``l`` is bound to the very object ``r`` names, and the append is a
store on that object.

The law: the helper's body is substituted with each formal bound to the
caller's actual, as its node-specialized frame is, and the formal's binding
after the body is the object after the call. Every name bound to the object
sees it. It is applied only when it is closed -- the actual itself, or cited
built-in container mutations of it over constants and formals -- and only
when the body is one path substitution can follow; a read keeps it only when
it is one plain completed value. Anything else keeps the havoc: unknown after
the call, never the pre-call contents. The helper's halts stay its faces at
the call.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import ListValue, SymbolicValue

from frame_fresh import fresh
from test_builtin_container_mutation import _halt_names, _ints, _only_return, _returns


def _unknown(value):
    return (
        type(value) is SymbolicValue
        and value.term.name == "python:receiver_after_call"
    )


ADD = "def add(l):\n    l.append(1)\n"


def test_a_helper_append_changes_the_callers_list(tmp_path):
    source = ADD + "def f():\n    r = []\n    add(r)\n    return r\n"
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_every_alias_sees_the_helpers_store(tmp_path):
    source = ADD + "def f():\n    r = []\n    a = r\n    add(r)\n    return a\n"
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_the_helpers_operands_come_from_the_call(tmp_path):
    source = (
        "def add(l, x):\n    l.append(x)\n    l.append(x)\n"
        "def f():\n    r = [0]\n    add(r, 5)\n    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(0, 5, 5))


def test_a_later_store_in_the_caller_builds_on_the_helpers(tmp_path):
    source = ADD + "def f():\n    r = []\n    add(r)\n    r.append(2)\n    return r\n"
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1, 2))


def test_an_assigned_call_still_applies_the_store(tmp_path):
    source = (
        "def add(l):\n    l.append(1)\n    return 7\n"
        "def f():\n    r = []\n    y = add(r)\n    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_helper_that_does_not_touch_the_list_leaves_it(tmp_path):
    source = (
        "def look(l):\n    n = len(l)\n    return n\n"
        "def f():\n    r = [3]\n    look(r)\n    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(3))


def test_a_name_that_only_contains_the_list_is_unknown(tmp_path):
    source = ADD + "def f():\n    r = []\n    outer = [r]\n    add(r)\n    return outer\n"
    assert _unknown(_only_return(tmp_path, source))


def test_a_helper_that_hands_the_list_to_unprojected_code_havocs(tmp_path):
    source = (
        "import copy\n"
        "def add(l):\n    copy.copy(l)\n"
        "def f():\n    r = []\n    add(r)\n    return r\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns and all(_unknown(value) for value in returns)


def test_a_helper_with_a_loop_havocs(tmp_path):
    source = (
        "def add(l):\n    for x in (1, 2):\n        l.append(x)\n"
        "def f():\n    r = []\n    add(r)\n    return r\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns and all(_unknown(value) for value in returns)


def test_a_helper_that_rebinds_its_formal_havocs(tmp_path):
    source = (
        "def add(l):\n    l = [9]\n    l.append(1)\n"
        "def f():\n    r = []\n    add(r)\n    return r\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns and all(_unknown(value) for value in returns)


def test_a_state_whose_store_would_raise_is_unknown_never_a_second_halt(tmp_path):
    # ``[].pop()`` raises: the read of ``r`` re-reads the helper's store, and a
    # store that halts there is not the call's completed path -- it is an
    # unknown, never ``[]`` and never a halt at the read.
    source = (
        "def take(l):\n    l.pop()\n"
        "def f():\n    r = []\n    take(r)\n    return r\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert all(_unknown(value) for value in returns)
    assert all("IndexError" not in str(getattr(h, "blame", "")) for h in halts)


def test_a_recursive_helper_is_followed_no_further(tmp_path):
    source = (
        "def add(l):\n    l.append(1)\n    add(l)\n"
        "def f():\n    r = []\n    add(r)\n    return r\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns and all(_unknown(value) for value in returns)
