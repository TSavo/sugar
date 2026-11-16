"""Two laws over values whose runtime type this frame did not decide.

1. ``==`` / ``!=`` between two values whose types are undecided (two calls'
   results) dispatches ``__eq__`` the lift did not look at.  It used to panic
   (``ComparisonOpSugar.Eq``: "undecided binary compare reached dual-edge
   path").  Now it is the #7585 two faces: it completes with the undecided
   ``py.eq`` predicate under ``python:compare.completes(..)`` and halts with an
   ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) under the
   complement.  Two decided builtin operands still complete outright.

2. A same-module generator function (``def``, ``async def`` or a
   ``@contextmanager`` generator) at a sync ``with`` head: its call is its
   coordinate and edge, joined at prove (#7757 step 6), so what it returns is
   what its contract states and the ``with`` enters an undecided manager,
   owed.  Verdict moved: an undecorated generator head was decided to raise
   the interpreter's ``TypeError`` (``GeneratorObjectWithSugar``), and a
   ``@contextmanager`` head ran the generator to its first yield.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import PredicateValue, TermValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

OPAQUE = "import textwrap\n"


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        h.producer_node_owner for h in halts if isinstance(h, UndeterminedRaiseEffect)
    )


def test_eq_of_two_call_results_is_two_faced(tmp_path):
    source = OPAQUE + (
        "def f():\n    return textwrap.dedent('a') == textwrap.dedent('b')\n"
    )
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is PredicateValue
    # The truth of the undecided ``==``'s value, keyed per evaluation
    # (#7757 NEW-1).
    assert value.formula.name == "python:truth_result"
    assert value.formula.args[0].name == "python:compare_result"
    assert value.formula.args[0].args[0].value == "Eq"
    assert "UndecidedCompare:Eq" in _owners(halts)


def test_ne_of_two_call_results_negates_and_may_raise(tmp_path):
    source = OPAQUE + (
        "def f():\n    return textwrap.dedent('a') != textwrap.dedent('b')\n"
    )
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is PredicateValue
    assert value.formula.kind == "not"
    # ``!=`` stands on the equals floor: the one undecided equality's halt
    # (#7757), its completed truth negated.
    assert "UndecidedCompare:Eq" in _owners(halts)


def test_the_compare_raise_reaches_an_except_arm(tmp_path):
    source = OPAQUE + (
        "def f():\n"
        "    try:\n"
        "        return textwrap.dedent('a') == textwrap.dedent('b')\n"
        "    except BaseException:\n"
        "        return 7\n"
    )
    returns, halts = _split(tmp_path, source)
    assert TermValue(7) in returns
    assert any(type(value) is PredicateValue for value in returns)
    assert halts == []


def test_decided_builtin_operands_complete_outright(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return 1 == 1\n")
    assert len(returns) == 1
    assert "UndecidedCompare:Eq" not in _owners(halts)


def _undecided_manager(tmp_path, source):
    """The With over a same-module generator function's call: the call is
    its coordinate and edge (#7757 step 6), so the head's value is undecided
    and the With enters an undecided manager.  No ``TypeError`` is decided,
    and the call and the manager steps owe their undecided halts."""
    returns, halts = _split(tmp_path, source)
    assert not [h for h in halts if getattr(h, "exception_name", None) == "TypeError"]
    assert any(isinstance(h, UndeterminedRaiseEffect) for h in halts)
    return returns, halts


def test_a_local_generator_at_a_with_head_is_the_undecided_manager(tmp_path):
    returns, _halts = _undecided_manager(
        tmp_path,
        "def gen():\n    yield 1\ndef f():\n    with gen():\n        return 1\n",
    )
    assert TermValue(1) in returns


def test_a_local_async_generator_at_a_with_head_is_the_undecided_manager(tmp_path):
    returns, _halts = _undecided_manager(
        tmp_path,
        "async def agen():\n    yield 1\n"
        "def f():\n    with agen():\n        return 1\n",
    )
    assert TermValue(1) in returns


def test_a_local_contextmanager_is_the_undecided_manager(tmp_path):
    source = (
        "import contextlib\n"
        "@contextlib.contextmanager\n"
        "def cm():\n    yield 1\n"
        "def f():\n    with cm():\n        return 1\n"
    )
    returns, _halts = _undecided_manager(tmp_path, source)
    assert TermValue(1) in returns
