"""``< <= > >=`` over operands whose runtime types are undecided.

Two calls' results (or a call's result against a number) select ``__lt__`` /
``__le__`` / ``__gt__`` / ``__ge__`` and their reflections, which the lift did
not look at.  Ordering used to refuse (``SugarNotWritten`` in
``FloorValue.less_than_from_left``).  Now it has the same two faces as ``==``
(#7620): the undecided ``py.lt/le/gt/ge`` predicate completes only under
``python:compare.completes(python:compare(op, site))`` and an
``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) halts under the
complement.  Decided builtin operands still fold, and incomparable decided
builtins (``1 < 'a'``) still halt with a ground ``TypeError``.

A chained comparison ``a < b < c`` evaluates ``b`` once and short-circuits as
CPython does: ``c`` and the second comparison run only when the first
comparison is truthy, and a raise from the first comparison ends the chain.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import PredicateValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

OPAQUE = "import textwrap\n"
SITE = "undecided-ordering-site"

_OPS = {"<": ("Lt", "py.lt"), "<=": ("LtE", "py.le"), ">": ("Gt", "py.gt"), ">=": ("GtE", "py.ge")}


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [(payload, guard) for kind, payload, guard in rows if kind == "return"]
    halts = [(payload, guard) for kind, payload, guard in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        h.producer_node_owner
        for h, _ in halts
        if isinstance(h, UndeterminedRaiseEffect)
    )


@pytest.mark.parametrize(
    "method,op",
    [("less_than", "<"), ("less_equal", "<="), ("greater_than", ">"), ("greater_equal", ">=")],
)
def test_floor_ordering_on_a_call_result_is_two_faced(method, op):
    left = CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
    result = getattr(left, method)(TermValue(1), SITE)
    assert isinstance(result, ExitSet)
    (completed,) = [face for face in result.exits if isinstance(face, Completed)]
    (halted,) = [face for face in result.exits if isinstance(face, Halted)]
    op_kind, atom = _OPS[op]
    assert completed.guard.name == "python:compare.completes"
    assert completed.value.formula.name == atom
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == f"UndecidedCompare:{op_kind}"


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_ordering_two_call_results_completes_undecided_or_raises(tmp_path, op):
    source = OPAQUE + (
        f"def f():\n    return textwrap.dedent('a') {op} textwrap.dedent('b')\n"
    )
    returns, halts = _split(tmp_path, source)
    ((value, _),) = returns
    op_kind, atom = _OPS[op]
    assert type(value) is PredicateValue
    assert value.formula.name == atom
    assert f"UndecidedCompare:{op_kind}" in _owners(halts)


def test_a_number_against_a_call_result_reflects_and_is_two_faced(tmp_path):
    source = OPAQUE + "def f():\n    return 1 < textwrap.dedent('b')\n"
    returns, halts = _split(tmp_path, source)
    ((value, _),) = returns
    assert value.formula.name == "py.lt"
    assert value.formula.args[0] == TermValue(1).to_term(owner="test")
    assert "UndecidedCompare:Lt" in _owners(halts)


def test_the_ordering_raise_reaches_an_except_arm(tmp_path):
    source = OPAQUE + (
        "def f():\n"
        "    r = textwrap.dedent('b')\n"
        "    try:\n"
        "        return r < 3\n"
        "    except BaseException:\n"
        "        return 7\n"
    )
    returns, halts = _split(tmp_path, source)
    values = [value for value, _ in returns]
    assert TermValue(7) in values
    assert any(type(value) is PredicateValue for value in values)
    assert "UndecidedCompare:Lt" not in _owners(halts)


def test_decided_builtin_ordering_is_unchanged(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return 1 < 2\n")
    assert len(returns) == 1 and halts == []
    (tmp_path / "te").mkdir()
    returns, halts = _split(tmp_path / "te", "def f():\n    return 1 < 'a'\n")
    assert returns == []
    ((halt, _),) = halts
    assert isinstance(halt, RaiseEffect)
    assert halt.exception_name == "TypeError"


def _mentions(term, text):
    return text in str(term)


def test_a_chain_evaluates_its_middle_once_and_short_circuits(tmp_path):
    source = OPAQUE + (
        "def f():\n"
        "    return 1 < textwrap.dedent('b') < textwrap.indent('c', 'd')\n"
    )
    returns, halts = _split(tmp_path, source)
    owners = _owners(halts)
    # The middle operand is called once; the right operand once.
    assert owners.count("UnknownCallee:textwrap.dedent") == 1
    assert owners.count("UnknownCallee:textwrap.indent") == 1
    # Two comparisons, each two-faced.
    assert owners.count("UndecidedCompare:Lt") == 2
    # Two returns: the first comparison's falsy value, or the second's value.
    assert len(returns) == 2
    first = [v for v, _ in returns if v.formula.args[0] == TermValue(1).to_term(owner="t")]
    assert len(first) == 1
    # The right operand runs only when the first comparison is truthy: its
    # call's halt is guarded by the first comparison's predicate, never its
    # negation.
    (indent_halt_guard,) = [
        g
        for h, g in halts
        if getattr(h, "producer_node_owner", None) == "UnknownCallee:textwrap.indent"
    ]
    first_atom = str(first[0].formula)
    assert first_atom in str(indent_halt_guard)
    assert f"_Connective(kind='not', operands=({first_atom}" not in str(indent_halt_guard)
