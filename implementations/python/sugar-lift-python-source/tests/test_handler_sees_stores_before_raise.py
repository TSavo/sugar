"""An exception handler, and ``finally``, see every store made before the raise.

``r = []; try: r.append(1); raise ValueError; except ValueError: return r``
lifted as returning ``[]``: the halt edges reaching the handler disagreed on
``r`` (the append's own edge carries ``[]``, the raise's carries ``[1]``), and a
name the edges disagreed on fell back to the PRE-TRY state -- a state no edge
carries.  Now a disagreeing name is joined over ``try-edge`` slots, one per body
statement, and the routed halt grounds them from its own occurrence: the handler
reads the state of the statement that actually raised.  A halt raised inside a
callee names the call it left through (``call_site_value.call_owned``).  A
source helper whose state for an actual holds at every halt inside it carries
that state at its halt, as on its completed path; any other statement that may
change an object and then raise (an opaque call, a loop, a helper that may halt
before its store) carries that object as unknown at its halt, never as the
state it began with.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import ListValue, NoneValue, SymbolicValue, TermValue

from frame_fresh import fresh
from test_builtin_container_mutation import _ints, _only_return, _returns


def test_append_then_raise_is_seen_by_the_handler(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.append(1)\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_store_through_an_alias_is_seen_by_the_handler(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    s = r\n"
        "    try:\n"
        "        s.append(1)\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_loops_stores_are_seen_by_the_handler(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        for i in (1, 2):\n"
        "            r.append(i)\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1, 2))


def test_pop_then_raise_is_seen_by_the_handler(tmp_path):
    source = (
        "def f():\n"
        "    r = [1, 2]\n"
        "    try:\n"
        "        r.pop()\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_cited_call_that_raises_has_not_stored(tmp_path):
    # ``[].pop()`` raises IndexError before it changes the list.
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.pop()\n"
        "    except IndexError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, ())


def test_finally_after_an_uncaught_raise_sees_the_stores(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.append(1)\n"
        "        raise ValueError()\n"
        "    finally:\n"
        "        return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_an_opaque_halt_after_a_store_is_seen_by_the_handler(tmp_path):
    source = (
        "import os\n"
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.append(1)\n"
        "        os.getpid()\n"
        "    except OSError:\n"
        "        return r\n"
        "    return None\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert fresh(ListValue, _ints(1)) in returns
    assert fresh(ListValue, ()) not in returns


def test_each_halt_site_hands_the_handler_its_own_binding(tmp_path):
    source = (
        "import os\n"
        "def f():\n"
        "    x = 1\n"
        "    try:\n"
        "        os.getpid()\n"
        "        x = 2\n"
        "        os.getpid()\n"
        "    except OSError:\n"
        "        return x\n"
        "    return None\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert TermValue(1) in returns
    assert TermValue(2) in returns
    assert NoneValue() in returns


def test_a_helper_that_stores_then_raises_hands_the_handler_its_store(tmp_path):
    # The append ran before the raise, on the caller's own list: the halt
    # leaving ``add`` carries the state the completed path would (#7757).
    source = (
        "def add(l):\n"
        "    l.append(1)\n"
        "    raise ValueError()\n"
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        add(r)\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_helper_that_may_raise_before_its_store_leaves_the_actual_unknown(
    tmp_path,
):
    # ``check()`` may raise before the append: a halt from ``add`` may carry
    # ``[]`` or ``[1]``, so the handler reads an unknown, never either.
    source = (
        "def check():\n"
        "    return 0\n"
        "def add(l):\n"
        "    check()\n"
        "    l.append(1)\n"
        "    raise ValueError()\n"
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        add(r)\n"
        "    except ValueError:\n"
        "        return r\n"
        "    return None\n"
    )
    value = _only_return(tmp_path, source)
    assert value != fresh(ListValue, ())
    assert value != fresh(ListValue, _ints(1))
    assert type(value) is SymbolicValue
    assert value.term.name == "python:receiver_after_call"


def test_finally_after_an_arm_reraises_never_claims_an_earlier_state(tmp_path):
    # The arm stores and re-raises: ``finally`` sees [1, 2].  The arm may halt
    # after any of its stores, so its halt carries ``r`` unknown -- never the
    # body's [1] nor the pre-try [].
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.append(1)\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        r.append(2)\n"
        "        raise\n"
        "    finally:\n"
        "        return r\n"
    )
    value = _only_return(tmp_path, source)
    assert value not in (fresh(ListValue, ()), fresh(ListValue, _ints(1)))


def test_finally_after_a_caught_raise_sees_the_arms_stores(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.append(1)\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        r.append(2)\n"
        "    finally:\n"
        "        r.append(3)\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1, 2, 3))
