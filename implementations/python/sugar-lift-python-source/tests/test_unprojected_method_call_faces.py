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

A formal receiver or operand defers to the caller's actual through the
``method_call`` carrier; a place a call may have changed stays the coordinate.
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


def test_a_formal_receiver_waits_for_the_caller(tmp_path):
    # The caller's actual selects the method; this frame mints no face, and
    # the undischarged ``method_call`` carrier is never a completion.
    from test_formal_method_call_defers import _carrier

    _carrier(tmp_path, "def f(y):\n    return y.foo()\n")


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
