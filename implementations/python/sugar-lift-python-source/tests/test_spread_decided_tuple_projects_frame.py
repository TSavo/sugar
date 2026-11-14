"""``g(*t)`` over a decided tuple projects the callee's source frame.

Python's call-time ``*`` unpacking puts the tuple's elements, in order, at
that position of the positional roster.  When the operand reduces to a decided
``TupleValue`` and the callee is an ordinary source function, the spread call
binds those elements onto the callee's formals and carries its body, exactly
as the non-spread call does.  Any other operand keeps the call two-faced
(#7633).  Reproducer: numpy's ``printoptions``
(``token = _set_printoptions(*args, **kwargs)`` with ``args == ()``).
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Halted

from test_undetermined_raise_except_matching import _exits


def _spread_halts(exits):
    return [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner.startswith("UnknownCallee:")
    ]


def _returns(exits):
    rows = []
    for face in exits.exits:
        if isinstance(face, Halted):
            continue
        for entry in face.value.record.statements:
            rows.append(entry.value)
    return rows


def test_a_decided_tuple_splat_reduces_through_the_callee_body(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(x):\n    return x\n"
        "def f():\n    if g(*(1,)) == 1:\n        return 7\n    raise ValueError\n",
    )
    assert _spread_halts(exits) == []
    assert [value.value for value in _returns(exits)] == [7]
    assert not any(isinstance(face, Halted) for face in exits.exits)


def test_splatted_elements_take_their_position_in_the_roster(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(x, y, z):\n    return y\n"
        "def f():\n    if g(1, *(2,), 3) == 2:\n        return 7\n    raise ValueError\n",
    )
    assert _spread_halts(exits) == []
    assert [value.value for value in _returns(exits)] == [7]


def test_an_empty_tuple_splat_with_a_decided_mapping_binds_the_keywords(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(*a, **k):\n    return k['p']\n"
        "def f():\n    if g(*(), **{'p': 3}) == 3:\n        return 7\n"
        "    raise ValueError\n",
    )
    assert _spread_halts(exits) == []
    assert [value.value for value in _returns(exits)] == [7]


def test_an_undecided_star_operand_stays_two_faced(tmp_path):
    exits = _exits(
        tmp_path, "def g(*x):\n    return 1\ndef f(*a):\n    return g(*a)\n"
    )
    assert [face.effect.producer_node_owner for face in _spread_halts(exits)] == [
        "UnknownCallee:g"
    ]
