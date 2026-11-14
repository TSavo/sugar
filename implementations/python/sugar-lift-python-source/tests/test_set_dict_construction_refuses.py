"""``set(...)``/``dict(...)`` over decided members follow CPython, refusals too.

``set([[1]])`` lifted as a set holding a list, and ``set([1, 1])`` as a set of
two members: the members were copied without hashing.  ``dict([1])`` and
``dict([(1,)])`` lifted as an opaque call that always completes.  CPython walks
the members in order: an unhashable member/key raises ``TypeError``, a pair
item that is not iterable raises ``TypeError`` and one of the wrong length
``ValueError``; equal members collapse (the set keeps the first, the dict
keeps the first key's position and the last value).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import DictValue, SetValue, StringValue, TermValue

from frame_fresh import fresh
from test_builtin_container_mutation import _ints, _only_return, _returns


def _ground_halt(tmp_path, expression):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert returns == []
    (halt,) = halts
    return halt.exception_name


@pytest.mark.parametrize(
    "expression, name",
    [
        ("set([[1]])", "TypeError"),
        ("set([1, {}])", "TypeError"),
        ("set(([1], 2))", "TypeError"),
        ("dict([1])", "TypeError"),
        ("dict([None])", "TypeError"),
        ("dict([(1,)])", "ValueError"),
        ("dict([(1, 2, 3)])", "ValueError"),
        ("dict([([1], 2)])", "TypeError"),
    ],
)
def test_a_refused_construction_raises_its_cpython_exception(tmp_path, expression, name):
    assert _ground_halt(tmp_path, expression) == name


def test_equal_set_members_collapse_to_the_first(tmp_path):
    value = _only_return(tmp_path, "def f():\n    return set([1, 2, 1])\n")
    assert value == fresh(SetValue, _ints(1, 2))


def test_a_repeated_dict_key_keeps_its_position_and_takes_the_last_value(tmp_path):
    value = _only_return(
        tmp_path, "def f():\n    return dict([(1, 'a'), (2, 'b'), (1, 'c')])\n"
    )
    assert value == fresh(
        DictValue,
        ((TermValue(1), StringValue("c")), (TermValue(2), StringValue("b"))),
    )


def test_the_first_bad_item_decides_the_exception(tmp_path):
    # ``(1,)`` is reached before ``[1]`` would be: ValueError, not TypeError.
    assert _ground_halt(tmp_path, "dict([(1,), 5])") == "ValueError"


@pytest.mark.parametrize("expression", ["{[1]}", "{1, {}}", "{[1]: 2}", "{1: 2, (3, [4]): 5}"])
def test_an_unhashable_display_member_raises_type_error(tmp_path, expression):
    assert _ground_halt(tmp_path, expression) == "TypeError"


def test_equal_set_display_members_collapse(tmp_path):
    assert _only_return(tmp_path, "def f():\n    return {1, 2, 1}\n") == fresh(
        SetValue, _ints(1, 2)
    )


def test_a_repeated_dict_display_key_takes_the_last_value(tmp_path):
    value = _only_return(tmp_path, "def f():\n    return {1: 'a', 2: 'b', 1: 'c'}\n")
    assert value == fresh(
        DictValue,
        ((TermValue(1), StringValue("c")), (TermValue(2), StringValue("b"))),
    )


def test_a_decided_equal_member_collapses_past_an_undecided_one(tmp_path):
    # ``1`` meets the first ``1`` before ``x``: CPython keeps one of them.
    (value,) = _returns(tmp_path, "def f(x):\n    return {1, x, 1}\n")[0]
    assert type(value) is SetValue and len(value.elements) == 2
    assert value.elements[0] == TermValue(1)


@pytest.mark.parametrize(
    "source",
    [
        "def f(x):\n    return len({x, 1})\n",
        "def f(x):\n    return len({x: 1, 2: 3})\n",
    ],
)
def test_members_of_undecided_equality_are_not_counted(tmp_path, source):
    # ``x`` may equal ``1``/``2``: the table may hold one member, not two.
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    (value,) = _returns(tmp_path, source)[0]
    assert type(value) is CallSiteValue and value.target_name == "len"


@pytest.mark.parametrize(
    "source, count",
    [
        ("def f():\n    return len({1, 2, 1})\n", 2),
        ("def f():\n    return len({1: 2, True: 3})\n", 1),
    ],
)
def test_decided_members_are_counted_after_collapse(tmp_path, source, count):
    assert _only_return(tmp_path, source) == TermValue(count)
