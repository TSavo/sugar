"""``d[k]`` on a dict the lift built, with a key it cannot compare, is two-faced.

CPython hashes ``k`` and compares it (``is``, then ``==``) with each stored
key; for a key of undecided type those may raise anything, and the lookup may
find any entry or none.  It used to refuse (``undecided receiver runtime type
or index semantics: DictValue[...]``) -- numpy's ``get_printoptions`` indexes
a literal dict with ``opts['legacy']``.  Now the #7587 opaque-subscript law
applies: the symbolic ``py.subscript(<dict>, <key>)`` completes under
``python:subscript.completes(...)`` and the complement halts with an
``UndeterminedRaiseEffect``.  A formal key still waits for the caller's actual.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def test_an_unknown_key_completes_symbolically_or_raises(tmp_path):
    returns, halts = _split(
        tmp_path, "def f():\n    return {1: 'a', 2: 'b'}[h()]\n"
    )
    (value,) = returns
    assert isinstance(value, SymbolicValue)
    assert value.term.name == "py.subscript"
    owners = sorted(
        halt.producer_node_owner
        for halt in halts
        if isinstance(halt, UndeterminedRaiseEffect)
    )
    assert owners == ["DictValue.subscript", "UnknownCallee:h"]


def test_a_decided_key_still_folds(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return {1: 'a', 2: 'b'}[2]\n")
    assert returns == [StringValue("b")]
    assert halts == []


def test_a_formal_key_is_decided_by_the_caller(tmp_path):
    source = (
        "def m(k):\n"
        "    return {1: 'a', 2: 'b'}[k]\n"
        "def f():\n"
        "    return m(2)\n"
    )
    _returns, halts = _split(tmp_path, source)
    assert not any(
        getattr(halt, "producer_node_owner", None) == "DictValue.subscript"
        for halt in halts
    )
