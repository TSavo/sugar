"""``in`` / ``not in`` over a container whose runtime type is undecided.

A call's result (``textwrap.dedent('b')``) has no decided type, so ``1 in r``
dispatches a ``__contains__`` (or iteration plus ``__eq__``) the lift did not
look at.  It used to refuse (``SugarNotWritten`` in ``CallSiteValue.contains``).
Now it is the #7620 two faces: the undecided ``py.in(item, container)``
predicate completes only under ``python:compare.completes(python:compare("In",
site))`` and an ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:In``)
halts under the complement.  ``not in`` dispatches the same ``__contains__``
and negates the completed face only.  Decided builtin receivers keep their
own laws.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import PredicateValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

OPAQUE = "import textwrap\n"
SITE = "undecided-membership-site"


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        h.producer_node_owner for h in halts if isinstance(h, UndeterminedRaiseEffect)
    )


def test_floor_membership_on_a_call_result_is_two_faced():
    container = CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
    result = container.contains(TermValue(1), SITE)
    assert isinstance(result, ExitSet)
    (completed,) = [face for face in result.exits if isinstance(face, Completed)]
    (halted,) = [face for face in result.exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert completed.value.formula.name == "py.in"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"


def test_in_on_a_call_result_completes_undecided_or_raises(tmp_path):
    source = OPAQUE + "def f():\n    return 1 in textwrap.dedent('b')\n"
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is PredicateValue
    assert value.formula.name == "py.in"
    assert "UndecidedCompare:In" in _owners(halts)


def test_not_in_negates_the_completed_face_only(tmp_path):
    source = OPAQUE + "def f():\n    return 'a' not in textwrap.dedent('b')\n"
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is PredicateValue
    assert value.formula.kind == "not"
    assert value.formula.operands[0].name == "py.in"
    assert "UndecidedCompare:In" in _owners(halts)


def test_the_membership_raise_reaches_an_except_arm(tmp_path):
    source = OPAQUE + (
        "def f():\n"
        "    r = textwrap.dedent('b')\n"
        "    try:\n"
        "        return 1 in r\n"
        "    except BaseException:\n"
        "        return 7\n"
    )
    returns, halts = _split(tmp_path, source)
    assert TermValue(7) in returns
    assert any(type(value) is PredicateValue for value in returns)
    assert "UndecidedCompare:In" not in _owners(halts)


def test_a_formal_container_discharged_onto_a_call_result_is_two_faced(tmp_path):
    source = OPAQUE + (
        "def g(xs):\n    return 1 in xs\n"
        "def f():\n    return g(textwrap.dedent('b'))\n"
    )
    returns, halts = _split(tmp_path, source)
    # g's return is its own call result (#7619); the membership inside g's
    # body raises from g's frame under the caller's occurrence.
    assert len(returns) == 1
    assert "UndecidedCompare:In" in _owners(halts)


def test_decided_builtin_containers_keep_their_laws(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return 'a' in 'abc'\n")
    assert len(returns) == 1
    assert _owners(halts) == []
    (tmp_path / "none").mkdir()
    returns, halts = _split(tmp_path / "none", "def f():\n    return 1 in None\n")
    assert returns == []
    (halt,) = halts
    assert isinstance(halt, RaiseEffect)
    assert halt.exception_name == "TypeError"
