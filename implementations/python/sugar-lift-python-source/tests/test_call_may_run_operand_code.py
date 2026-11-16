"""A call that may run code holding an object leaves that object unknown.

``c = C(); c.add(); return c.items`` lifted as returning the list ``__init__``
built: the object's place was marked invalidated at the call, but a read of an
invalidated place fell back to the constructed (pre-call) object. The same
held for ``foo(c)``, ``x = g(c)``, and for builtins cited pure that invoke the
operand's dunders -- ``print(c)`` runs ``c.__str__``, ``sum([c])`` runs
``c.__radd__``, ``sorted(c)`` runs ``c.__iter__``, ``f'{c}'`` runs
``c.__format__`` -- any of which may mutate ``c``.

The law: a call changes nothing it is handed only when it is a cited pure
builtin whose operands are builtin-typed all the way down (so every dunder it
invokes is CPython's own), or one of ``id``/``type``/``isinstance``/
``issubclass``/``callable``, which invoke no operand dunder. Any other call,
and any f-string field over a non-builtin value, leaves every object it may
reach unknown afterwards: the object reads as an unknown minted at the call,
never as its pre-call contents.

A call of a same-file definition is its coordinate and edge (#7757 steps 6
and 9): ``C()`` is the class call nothing here answers, and a call handed
``c`` leaves it as ``python:after(<call result>, <label>)``, the one spelling
of an object's state after a call that the callee's contract states its post
over (``source_call_resolution.object_after_call``).  An operation nothing
decides leaves it as ``python:receiver_after_call``.  Either is unknown here:
never the pre-call object.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

from frame_fresh import fresh
from test_builtin_container_mutation import _only_return, _returns

CLS = (
    "class C:\n"
    "    def __init__(self):\n"
    "        self.items = [5]\n"
    "    def add(self):\n"
    "        self.items.append(1)\n"
    "    def __str__(self):\n"
    "        self.items.append(1)\n"
    "        return 'c'\n"
    "    def __radd__(self, other):\n"
    "        self.items.append(1)\n"
    "        return 0\n"
    "    def __iter__(self):\n"
    "        self.items.append(1)\n"
    "        return iter([])\n"
    "    def __format__(self, spec):\n"
    "        self.items.append(1)\n"
    "        return 'c'\n"
    "def g(o):\n"
    "    o.items.append(2)\n"
    "    return 0\n"
)


def _unknown_after_call(value):
    return type(value) is SymbolicValue and value.term.name in {
        "python:receiver_after_call",
        "python:after",
    }


@pytest.mark.parametrize(
    "call",
    [
        "c.add()",
        "foo(c)",
        "x = g(c)",
        "print(c)",
        "x = str(c)",
        "x = sum([c])",
        "x = sorted(c)",
        "x = list(c)",
        "x = f'{c}'",
        "print([1, c])",
    ],
)
def test_an_object_a_call_may_change_is_unknown_after_it(tmp_path, call):
    source = CLS + f"def f():\n    c = C()\n    {call}\n    return c\n"
    (value,), _halts = _returns(tmp_path, source)
    assert _unknown_after_call(value)


@pytest.mark.parametrize(
    "call, name",
    [
        ("print(c)", "print"),
        ("x = str(c)", "str"),
        ("x = sum([c])", "sum"),
        ("x = sorted([c, c])", "sorted"),
        ("x = f'{c}'", "format"),
        ("x = repr([1, c])", "repr"),
    ],
)
def test_a_builtin_running_a_user_dunder_may_raise(tmp_path, call, name):
    # ``C.__str__``/``__len__``/... raise ValueError: the builtin is not
    # total, so the handler is reachable.  The dunder is not CPython's own,
    # so the call is the one unanswered call (#7757).  ``C()`` before the
    # ``try`` is the class call, owed: its own halt leaves ``f`` too.
    source = (
        "class C:\n"
        "    def __str__(self):\n"
        "        raise ValueError('x')\n"
        f"def f():\n    c = C()\n    try:\n        {call}\n"
        "    except ValueError:\n        return 'caught'\n    return 'no'\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert sorted(value.value for value in returns) == ["caught", "no"]
    assert all(type(halt) is UndeterminedRaiseEffect for halt in halts)
    assert sorted({halt.producer_node_owner for halt in halts}) == sorted(
        {"UnknownCallee:e.C", f"UnknownCallee:{name}"}
    )


@pytest.mark.parametrize(
    "call", ["x = str(3)", "x = len([1, 'a'])", "print(1, (2, None))", "x = f'{1}'"]
)
def test_a_builtin_over_builtin_operands_stays_total(tmp_path, call):
    source = (
        f"def f():\n    try:\n        {call}\n"
        "    except ValueError:\n        return 'caught'\n    return 'no'\n"
    )
    assert _only_return(tmp_path, source).value == "no"


@pytest.mark.parametrize(
    "call",
    [
        "print(1, 'a')",
        "print([1, (2, 'x')])",
        "x = len([1, 2])",
        "x = sum([1, 2])",
        "x = sorted([2, 1])",
        "x = str(3)",
        "x = f'{1}'",
        "x = type(c)",
        "x = id(c)",
    ],
)
def test_a_builtin_over_builtin_operands_changes_nothing(tmp_path, call):
    # ``c`` is a list the frame built: the class call's instance is the
    # constructor contract's to state at prove, never a field read off
    # ``__init__`` here (#7757), so the object the builtins must leave alone
    # is one the lift decides.
    source = CLS + f"def f():\n    c = [5]\n    {call}\n    return c\n"
    assert _only_return(tmp_path, source) == fresh(ListValue, (TermValue(5),))


@pytest.mark.parametrize("call", ["x = type(c)", "x = id(c)"])
def test_type_and_id_run_no_dunder_of_a_class_calls_instance(tmp_path, call):
    # ``type``/``id`` invoke no operand dunder: the instance is the class
    # call's own result after them, never an object a call may have changed.
    source = CLS + f"def f():\n    c = C()\n    {call}\n    return c\n"
    returns, halts = _returns(tmp_path, source)
    (value,) = returns
    assert not _unknown_after_call(value)
    assert value.term.name == "python:call_result"
    assert value.term.args[0].name == "call:e.C"
    assert sorted({halt.producer_node_owner for halt in halts}) == [
        "UnknownCallee:e.C"
    ]
