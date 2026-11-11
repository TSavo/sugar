"""Two laws over values whose runtime type this frame did not decide.

1. ``==`` / ``!=`` between two values whose types are undecided (two calls'
   results) dispatches ``__eq__`` the lift did not look at.  It used to panic
   (``ComparisonOpSugar.Eq``: "undecided binary compare reached dual-edge
   path").  Now it is the #7585 two faces: it completes with the undecided
   ``py.eq`` predicate under ``python:compare.completes(..)`` and halts with an
   ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) under the
   complement.  Two decided builtin operands still complete outright.

2. A same-module undecorated generator function (``def`` or ``async def``) at
   a sync ``with`` head returns a generator object, which has no
   ``__enter__``: the ``with`` raises the interpreter's own observed
   ``TypeError`` before enter and body (#7595's law, now in the single-file
   setup), never a runtime-selected gap.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import PredicateValue, TermValue
from sugar_lift_py_tests.generator_object_with_refusal import (
    observed_generator_object_with_refusal,
)

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
    assert value.formula.name == "py.eq"
    assert "UndecidedCompare:Eq" in _owners(halts)


def test_ne_of_two_call_results_negates_and_may_raise(tmp_path):
    source = OPAQUE + (
        "def f():\n    return textwrap.dedent('a') != textwrap.dedent('b')\n"
    )
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is PredicateValue
    assert value.formula.kind == "not"
    assert "UndecidedCompare:NotEq" in _owners(halts)


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


def _with_halts(tmp_path, source):
    returns, halts = _split(tmp_path, source)
    assert returns == []
    (halt,) = halts
    assert isinstance(halt, RaiseEffect)
    assert halt.producer_node_owner == "GeneratorObjectWithSugar"
    return halt


def test_a_local_generator_at_a_with_head_raises_type_error(tmp_path):
    halt = _with_halts(
        tmp_path,
        "def gen():\n    yield 1\ndef f():\n    with gen():\n        return 1\n",
    )
    refusal = observed_generator_object_with_refusal("generator")
    assert refusal.exception_name == "TypeError"
    assert halt.raised_value == refusal.message


def test_a_local_async_generator_at_a_with_head_raises_its_own_type_error(tmp_path):
    halt = _with_halts(
        tmp_path,
        "async def agen():\n    yield 1\n"
        "def f():\n    with agen():\n        return 1\n",
    )
    refusal = observed_generator_object_with_refusal("async_generator")
    assert refusal.exception_name == "TypeError"
    assert "async_generator" in refusal.message
    assert halt.raised_value == refusal.message


def test_the_with_body_and_handlers_never_run(tmp_path):
    source = (
        "def gen():\n"
        "    try:\n"
        "        yield 1\n"
        "    except ValueError:\n"
        "        pass\n"
        "def f():\n"
        "    with gen():\n"
        "        raise ValueError('v')\n"
    )
    _with_halts(tmp_path, source)


def test_a_local_contextmanager_is_still_a_manager(tmp_path):
    source = (
        "import contextlib\n"
        "@contextlib.contextmanager\n"
        "def cm():\n    yield 1\n"
        "def f():\n    with cm():\n        return 1\n"
    )
    returns, _halts = _split(tmp_path, source)
    assert returns == [TermValue(1)]
