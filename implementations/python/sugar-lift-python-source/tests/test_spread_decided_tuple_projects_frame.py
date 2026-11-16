"""``g(*t)`` over a decided tuple is the call's coordinate and edge.

Python's call-time ``*`` unpacking puts the tuple's elements, in order, at
that position of the positional roster.  A same-file callee's body is not
reduced at lift (#7757 step 6, the owner 2026-11-15: a same-file call is a
coordinate and an edge joined at prove), so the spread call is the one
unanswered call, two-faced, its halt kept and owed: the roster is the call's
operands, and what ``g`` returns is joined at prove.  A comparison against
its result is never decided here by reading ``g``'s body, so the arm that
raises stays.  Reproducer: numpy's ``printoptions``
(``token = _set_printoptions(*args, **kwargs)`` with ``args == ()``).
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Halted

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _spread_halts(exits):
    return [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner.startswith("UnknownCallee:")
    ]


def the_call_is_owed_and_both_arms_stay(exits, callee):
    """The spread call is ``callee``'s one unanswered call (its halt kept);
    ``return 7`` is reachable and so is ``raise ValueError``."""
    assert [face.effect.producer_node_owner for face in _spread_halts(exits)] == [
        f"UnknownCallee:{callee}"
    ]
    rows = _rows(exits)
    assert TermValue(7) in [payload for kind, payload, _ in rows if kind == "return"]
    assert "ValueError" in [
        getattr(payload, "exception_name", None)
        for kind, payload, _ in rows
        if kind == "halt"
    ]


def test_a_decided_tuple_splat_is_the_call_owed(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(x):\n    return x\n"
        "def f():\n    if g(*(1,)) == 1:\n        return 7\n    raise ValueError\n",
    )
    the_call_is_owed_and_both_arms_stay(exits, "e.g")


def test_splatted_elements_in_the_roster_are_the_call_owed(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(x, y, z):\n    return y\n"
        "def f():\n    if g(1, *(2,), 3) == 2:\n        return 7\n    raise ValueError\n",
    )
    the_call_is_owed_and_both_arms_stay(exits, "e.g")


def test_an_empty_tuple_splat_with_a_decided_mapping_is_the_call_owed(tmp_path):
    exits = _exits(
        tmp_path,
        "def g(*a, **k):\n    return k['p']\n"
        "def f():\n    if g(*(), **{'p': 3}) == 3:\n        return 7\n"
        "    raise ValueError\n",
    )
    the_call_is_owed_and_both_arms_stay(exits, "e.g")


def test_an_undecided_star_operand_stays_two_faced(tmp_path):
    exits = _exits(
        tmp_path, "def g(*x):\n    return 1\ndef f(*a):\n    return g(*a)\n"
    )
    assert [face.effect.producer_node_owner for face in _spread_halts(exits)] == [
        "UnknownCallee:g"
    ]
