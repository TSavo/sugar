"""Each evaluation of a call whose body the lift reduced is its own result.

``def g(): return []`` / ``(g(), g())`` lifted as ``(call:g(), call:g())``:
one term for two evaluations, claiming both calls return the same object (and,
for a body that returns an opaque value, the same unknown).  The application
``call:g(..)`` stays the bridge coordinate (``CallSiteValue.term``); the value
one evaluation returned is ``python:call_result(<application>, <occurrence>)``,
keyed on the call site and the dynamic occurrence path it ran under (#7601), and
the callee's post is applied at that result term.  A body that returns one
ground immutable scalar returns it on every evaluation, so the result stays
ground.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import ListValue, TermValue, TupleValue

from test_unprojected_method_call_faces import _split


def _terms(value):
    return [element.to_term(owner="test") for element in value.elements]


def test_two_calls_of_one_helper_are_two_results(tmp_path):
    source = "def g():\n    return []\ndef f():\n    return (g(), g())\n"
    (value,), _halts = _split(tmp_path, source)
    assert type(value) is TupleValue
    first, second = _terms(value)
    assert first.name == second.name == "python:call_result"
    assert first.args[0] == second.args[0]
    assert first.args[0].name == "call:g"
    assert first != second


def test_each_comprehension_member_is_its_own_result(tmp_path):
    source = (
        "import textwrap\n"
        "def g():\n"
        "    return textwrap.dedent('a')\n"
        "def f():\n"
        "    return [g() for _ in range(2)]\n"
    )
    returns, _halts = _split(tmp_path, source)
    (value,) = returns
    assert type(value) is ListValue
    first, second = _terms(value)
    assert first.name == second.name == "python:call_result"
    assert first != second


def test_a_ground_scalar_return_stays_ground(tmp_path):
    source = "def g():\n    return 3\ndef f():\n    return (g(), g())\n"
    (value,), _halts = _split(tmp_path, source)
    assert _terms(value) == [TermValue(3).to_term(owner="t")] * 2


def test_one_evaluation_reads_the_same_result_twice(tmp_path):
    # A name bound to one call's result is that one result on every read.
    source = "def g():\n    return []\ndef f():\n    x = g()\n    return (x, x)\n"
    (value,), _halts = _split(tmp_path, source)
    first, second = _terms(value)
    assert first.name == "python:call_result"
    assert first == second


def test_the_callee_post_is_applied_at_the_result_term(tmp_path):
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    source = "def g():\n    return (1, 2)\ndef f():\n    return [g()]\n"
    (value,), _halts = _split(tmp_path, source)
    (element,) = value.elements
    assert type(element) is CallSiteValue
    residue = element.derived_equality_residue(None)
    assert residue is not None
    assert residue.args[0] == element.to_term(owner="test")
    assert residue.args[0].name == "python:call_result"
