"""A method call no floor of the receiver answers may raise, and each one
returns its own unknown.

``r.foo()`` on a call's opaque result, or ``'a'.index('b')`` on a str the lift
built, fell through to the bare ``call:foo(r)`` coordinate: it always
completed, so ``try: r.foo() except ValueError: ...`` had an unreachable
handler, and ``(r.foo(), r.foo())`` claimed both calls return the same object. The body that runs is selected by the receiver's runtime type
and was not looked at, so the call is two-faced (the #7585 law): it completes
under ``python:unknown_callee_call.completes(python:unknown_callee_call(name, site))`` with
the value ``python:call_result(<call term>, <occurrence>)``, and halts with an
``UndeterminedRaiseEffect`` (owner ``UnknownCallee:<name>``) under the
complement.

A formal receiver whose class is no input of the function's contract is this
same two-faced call, never a carrier waiting for the caller's actual (#7757
NEW-1); a place a call may have changed stays the coordinate.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue, TupleValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _guard in rows if kind == "return"]
    halts = [payload for kind, payload, _guard in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        halt.producer_node_owner
        for halt in halts
        if isinstance(halt, UndeterminedRaiseEffect)
    )


OPAQUE = "import textwrap\n"
RESULT = "textwrap.dedent('a')"


def test_a_method_call_on_an_opaque_result_may_raise(tmp_path):
    source = OPAQUE + f"def f():\n    {RESULT}.foo()\n    return 1\n"
    returns, halts = _split(tmp_path, source)
    assert returns == [TermValue(1)]
    assert "UnknownCallee:foo" in _owners(halts)


def test_its_raise_reaches_an_except_arm(tmp_path):
    source = OPAQUE + (
        "def f():\n"
        "    try:\n"
        f"        {RESULT}.foo()\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    return 1\n"
    )
    returns, halts = _split(tmp_path, source)
    # dedent and foo may each raise into the arm.
    assert {value.value for value in returns} == {1, 2}
    # ``except ValueError`` is not total: a non-ValueError raise still leaves.
    assert "UnknownCallee:foo" in _owners(halts)


def test_two_calls_are_two_unknowns(tmp_path):
    source = OPAQUE + "def f():\n    s = textwrap.dedent('a')\n    return (s.foo(), s.foo())\n"
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is TupleValue
    first, second = (element.to_term(owner="test") for element in value.elements)
    assert first.name == second.name == "python:call_result"
    assert first != second
    assert _owners(halts).count("UnknownCallee:foo") == 2


def test_a_str_method_may_refuse_by_value(tmp_path):
    # ``'a'.index('b')`` raises ValueError: the str method is not total.
    returns, halts = _split(tmp_path, "def f():\n    return 'a'.index('b')\n")
    assert "UnknownCallee:index" in _owners(halts)


def test_an_unanswered_method_call_is_two_faced_and_owes_one_call(tmp_path):
    # #7757: no floor of the str answers ``index``; the call is the one
    # unanswered form, one completed face and one raise, and owes one call.
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    exits = _exits(tmp_path, "def f():\n    return 'a'.index('b')\n")
    rows = _rows(exits)
    returns = [payload for kind, payload, _guard in rows if kind == "return"]
    halts = [payload for kind, payload, _guard in rows if kind == "halt"]
    assert len(returns) == 1
    assert _owners(halts) == ["UnknownCallee:index"]
    assert len(owed_calls(exits)) == 1


def test_a_formal_receiver_whose_class_is_no_input_is_two_faced(tmp_path):
    # ``y`` is read bare (``z = y``), so nothing binds its class: the call is
    # the one unanswered call, one completed face and one raise (#7757
    # NEW-1), never a carrier waiting for the caller's actual.
    returns, halts = _split(tmp_path, "def f(y):\n    z = y\n    return y.foo()\n")
    assert len(returns) == 1
    assert _owners(halts) == ["UnknownCallee:foo"]


def test_a_source_method_is_not_this_law(tmp_path):
    source = (
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
        "def f():\n"
        "    return C().m()\n"
    )
    _returns, halts = _split(tmp_path, source)
    assert "UnknownCallee:m" not in _owners(halts)
