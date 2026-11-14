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
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

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
    return (
        type(value) is SymbolicValue
        and value.term.name == "python:receiver_after_call"
    )


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
    # so the call is the one unanswered call (#7757).
    source = (
        "class C:\n"
        "    def __str__(self):\n"
        "        raise ValueError('x')\n"
        f"def f():\n    c = C()\n    try:\n        {call}\n"
        "    except ValueError:\n        return 'caught'\n    return 'no'\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert sorted(value.value for value in returns) == ["caught", "no"]
    (halt,) = halts
    assert type(halt) is UndeterminedRaiseEffect
    assert halt.producer_node_owner == f"UnknownCallee:{name}"


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
    source = CLS + f"def f():\n    c = C()\n    {call}\n    return c.items\n"
    assert _only_return(tmp_path, source) == ListValue((TermValue(5),))
