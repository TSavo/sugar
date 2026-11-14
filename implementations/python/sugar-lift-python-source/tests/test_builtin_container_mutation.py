"""A mutating method call on a built-in container changes the object.

``r = []; r.append(1); return r`` lifted as returning ``[]``: the append was an
opaque ``call:append`` coordinate and the list was never changed -- a false
claim. Now a method call whose receiver is decided as a ``list``/``dict``/
``set`` (the lifter's own ``ListValue``/``DictValue``/``SetValue``) is cited
from CPython's documented semantics: its effect is a store on the object, seen
through every name bound to that object; its decided exceptional exits
(``IndexError``, ``ValueError``, ``KeyError``, ``TypeError``) are faces at the
call; its value is CPython's (``append`` is ``None``, ``pop`` the element).

Where the receiver's type or the operands do not decide the effect, the call
stays opaque and the receiver's contents are unknown afterwards -- never the
pre-call contents.
"""

from __future__ import annotations

import re

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    NoneValue,
    SetValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _returns(tmp_path, source):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = _rows(_exits(tmp_path, source))
    return [payload for kind, payload, _guard in rows if kind == "return"], [
        payload for kind, payload, _guard in rows if kind == "halt"
    ]


def _only_return(tmp_path, source):
    returns, halts = _returns(tmp_path, source)
    assert halts == []
    (value,) = returns
    return value


def _ints(*values):
    return tuple(TermValue(value) for value in values)


def _is_unknown_after_call(value, label):
    return (
        type(value) is SymbolicValue
        and value.term.name == "python:receiver_after_call"
        and value.term.args[1].value == label
    )


def _halt_names(halts):
    return sorted(getattr(halt, "exception_name", None) or "" for halt in halts)


def test_append_then_return_is_the_appended_list(tmp_path):
    source = "def f():\n    r = []\n    r.append(1)\n    return r\n"
    assert _only_return(tmp_path, source) == ListValue(_ints(1))


def test_an_alias_sees_the_append(tmp_path):
    source = "def f():\n    r = []\n    a = r\n    r.append(1)\n    return a\n"
    assert _only_return(tmp_path, source) == ListValue(_ints(1))


def test_a_subscript_store_is_seen_through_an_alias(tmp_path):
    source = "def f():\n    r = [0]\n    a = r\n    r[0] = 5\n    return a\n"
    assert _only_return(tmp_path, source) == ListValue(_ints(5))


def test_pop_from_an_empty_list_raises_index_error_inside_the_try(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    try:\n"
        "        r.pop()\n"
        "    except IndexError:\n"
        "        return 'caught'\n"
        "    return 'no'\n"
    )
    assert _only_return(tmp_path, source) == StringValue("caught")


def test_pop_from_an_empty_list_is_the_calls_index_error(tmp_path):
    source = "def f():\n    r = []\n    r.pop()\n    return r\n"
    returns, halts = _returns(tmp_path, source)
    assert returns == []
    assert _halt_names(halts) == ["IndexError"]


def test_pop_returns_the_element_and_shortens_the_list(tmp_path):
    source = "def f():\n    r = [1, 2]\n    x = r.pop()\n    return (x, r)\n"
    assert _only_return(tmp_path, source) == TupleValue(
        (TermValue(2), ListValue(_ints(1)))
    )


def test_append_returns_none(tmp_path):
    source = "def f():\n    r = []\n    x = r.append(1)\n    return (x, r)\n"
    assert _only_return(tmp_path, source) == TupleValue(
        (NoneValue(), ListValue(_ints(1)))
    )


def test_extend_with_a_list(tmp_path):
    source = "def f():\n    r = [1]\n    r.extend([2, 3])\n    return r\n"
    assert _only_return(tmp_path, source) == ListValue(_ints(1, 2, 3))


def test_insert_remove_reverse_clear(tmp_path):
    source = (
        "def f():\n"
        "    r = [1, 2, 3]\n"
        "    r.insert(0, 9)\n"
        "    r.remove(2)\n"
        "    r.reverse()\n"
        "    a = list(r)\n"
        "    r.clear()\n"
        "    return (a, r)\n"
    )
    value = _only_return(tmp_path, source)
    assert value.elements[1] == ListValue(())


def test_remove_of_a_missing_member_is_value_error(tmp_path):
    source = (
        "def f():\n"
        "    r = [1, 2]\n"
        "    try:\n"
        "        r.remove(3)\n"
        "    except ValueError:\n"
        "        return 'missing'\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == StringValue("missing")


def test_augmented_add_mutates_the_object_every_alias_names(tmp_path):
    source = "def f():\n    r = [1]\n    a = r\n    r += [2]\n    return a\n"
    assert _only_return(tmp_path, source) == ListValue(_ints(1, 2))


def test_unrolled_loop_appends_one_distinct_unknown_per_iteration(tmp_path):
    source = (
        "import textwrap\n"
        "def f(s):\n"
        "    r = []\n"
        "    for i in range(2):\n"
        "        r.append(textwrap.dedent(s[i]))\n"
        "    return r\n"
    )
    returns, halts = _returns(tmp_path, source)
    (value,) = returns
    assert type(value) is ListValue and len(value.elements) == 2
    first, second = value.elements
    assert first != second
    # Each member names its evaluation by `python:occurrence(<site coordinate
    # CID>, <path segment>...)` (#7808): its loop segment is its iteration.
    iterations = []
    for member in (first, second):
        occurrence = member.term.args[1]
        assert occurrence.name == "python:occurrence"
        iterations.append(
            sorted(
                {
                    match.group(1)
                    for segment in occurrence.args[1:]
                    if (match := re.fullmatch(r"loop\[\d+,\d+\)#(\d)", segment.value))
                }
            )
        )
    assert iterations == [["0"], ["1"]]
    # Each iteration's call halts once, at its own occurrence.
    assert len(halts) == 2
    assert all(isinstance(halt, UndeterminedRaiseEffect) for halt in halts)
    assert len({halt.occurrence for halt in halts}) == 2


def test_a_list_passed_to_a_helper_is_what_its_body_leaves(tmp_path):
    # The helper's body is projected: its append is a store on ``r``'s object
    # (tests/test_source_helper_applies_actual_stores.py), never ``[]``.
    source = (
        "def g(x):\n"
        "    x.append(1)\n"
        "    return 1\n"
        "def f():\n"
        "    r = []\n"
        "    v = g(r)\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == ListValue(_ints(1))


def test_a_list_passed_to_unprojected_code_is_unknown_after_the_call(tmp_path):
    source = (
        "import copy\n"
        "def f():\n"
        "    r = []\n"
        "    v = copy.copy(r)\n"
        "    return r\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns and all(_is_unknown_after_call(value, "r") for value in returns)


def test_a_pure_builtin_does_not_change_its_argument(tmp_path):
    source = "def f():\n    r = [1]\n    n = len(r)\n    return (n, r)\n"
    assert _only_return(tmp_path, source) == TupleValue(
        (TermValue(1), ListValue(_ints(1)))
    )


def test_an_undecided_receiver_stays_opaque_and_is_unknown_after(tmp_path):
    # The formal's method waits for the caller's actual (the ``method_call``
    # carrier); once a list is supplied, ``x`` is unknown after the call.
    from test_formal_method_call_defers import _carrier, _discharge

    source = "def f(x):\n    x.append(1)\n    return x\n"
    exits = _discharge(_carrier(tmp_path, source), ListValue(()))
    (value,) = [payload for kind, payload, _ in _rows(exits) if kind == "return"]
    assert _is_unknown_after_call(value, "x")


def test_a_value_that_holds_the_list_is_unknown_after_its_mutation(tmp_path):
    source = (
        "def f():\n    r = []\n    outer = [r]\n    r.append(1)\n    return outer\n"
    )
    value = _only_return(tmp_path, source)
    assert value != ListValue((ListValue(()),))
    assert _is_unknown_after_call(value, "outer")


def test_a_symbolic_loop_leaves_the_list_unknown(tmp_path):
    source = (
        "def f(xs):\n    r = []\n    for x in xs:\n        r.append(x)\n    return r\n"
    )
    value = _only_return(tmp_path, source)
    assert value != ListValue(())
    assert _is_unknown_after_call(value, "r")


def test_remove_of_a_symbolic_member_is_two_faced_and_unknown_after(tmp_path):
    source = "def f(x):\n    r = [1, 2]\n    r.remove(x)\n    return r\n"
    returns, halts = _returns(tmp_path, source)
    (value,) = returns
    assert type(value) is SymbolicValue
    assert value.term.name == "python:builtin_method.post_state"
    (halt,) = halts
    assert isinstance(halt, UndeterminedRaiseEffect)
    assert halt.producer_node_owner == "BuiltinMethodCall:list.remove"


def test_dict_store_update_setdefault_and_delete(tmp_path):
    source = (
        "def f():\n"
        "    d = {}\n"
        "    d.update({'a': 1})\n"
        "    d['b'] = 2\n"
        "    v = d.setdefault('c', 3)\n"
        "    w = d.setdefault('a', 9)\n"
        "    del d['b']\n"
        "    return (d, v, w)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (
            DictValue(
                (
                    (StringValue("a"), TermValue(1)),
                    (StringValue("c"), TermValue(3)),
                )
            ),
            TermValue(3),
            TermValue(1),
        )
    )


def test_dict_pop_of_a_missing_key_is_key_error(tmp_path):
    source = (
        "def f():\n"
        "    d = {'a': 1}\n"
        "    try:\n"
        "        d.pop('b')\n"
        "    except KeyError:\n"
        "        return 'k'\n"
        "    return d\n"
    )
    assert _only_return(tmp_path, source) == StringValue("k")


def test_set_add_discard_and_an_unhashable_member(tmp_path):
    source = (
        "def f():\n"
        "    s = set()\n"
        "    s.add(1)\n"
        "    s.add(1)\n"
        "    s.discard(2)\n"
        "    return s\n"
    )
    assert _only_return(tmp_path / "a", source) == SetValue(_ints(1))
    source = "def f():\n    s = set()\n    s.add([1])\n    return s\n"
    returns, halts = _returns(tmp_path / "b", source)
    assert returns == []
    assert _halt_names(halts) == ["TypeError"]


def test_a_bool_member_is_the_equal_int(tmp_path):
    source = "def f():\n    s = {1}\n    s.add(True)\n    r = [0]\n    r.remove(False)\n    return (s, r)\n"
    assert _only_return(tmp_path, source) == TupleValue(
        (SetValue(_ints(1)), ListValue(()))
    )


def test_extend_from_a_multi_member_set_is_unknown_order(tmp_path):
    source = "def f():\n    r = []\n    r.extend({1, 2})\n    return r\n"
    returns, _halts = _returns(tmp_path, source)
    (value,) = returns
    assert type(value) is SymbolicValue
    assert value.term.name == "python:builtin_method.post_state"


def test_set_ior_with_a_list_is_not_update(tmp_path):
    source = "def f():\n    s = set()\n    s |= [1]\n    return s\n"
    returns, _halts = _returns(tmp_path, source)
    assert SetValue(_ints(1)) not in returns


def test_augmented_add_on_an_opaque_operand_leaves_one_object(tmp_path):
    source = (
        "def f(x):\n    r = [1]\n    a = r\n    r += x\n    return (a, r)\n"
    )
    returns, _halts = _returns(tmp_path, source)
    (value,) = returns
    first, second = value.elements
    assert first == second
    assert type(first) is SymbolicValue
