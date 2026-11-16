"""Each evaluation of a same-file call is its own result.

``def g(): return []`` / ``(g(), g())`` lifted as ``(call:g(), call:g())``:
one term for two evaluations, claiming both calls return the same object (and,
for a body that returns an opaque value, the same unknown).  The application
``call:<module>.g(..)`` stays the bridge coordinate (``CallSiteValue.term``);
the value one evaluation returned is ``python:call_result(<application>,
<occurrence>)``, keyed on the call site and the dynamic occurrence path it ran
under (#7601).  No callee body is read at lift (#7757 step 6): what the call
returns is joined at prove, so even a body returning one ground scalar is its
keyed result here.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import TupleValue

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
    # The target symbol is the callee's module-qualified name (step 7).
    assert first.args[0].name == "call:e.g"
    assert first != second


def test_a_ground_scalar_return_is_its_keyed_result(tmp_path):
    # ``g``'s ``return 3`` is not read at lift: each call is its keyed
    # result, the callee's contract applied at prove (#7757 step 6).
    source = "def g():\n    return 3\ndef f():\n    return (g(), g())\n"
    (value,), _halts = _split(tmp_path, source)
    first, second = _terms(value)
    assert first.name == second.name == "python:call_result"
    assert first.args[0].name == second.args[0].name == "call:e.g"
    assert first != second


def test_one_evaluation_reads_the_same_result_twice(tmp_path):
    # A name bound to one call's result is that one result on every read.
    source = "def g():\n    return []\ndef f():\n    x = g()\n    return (x, x)\n"
    (value,), _halts = _split(tmp_path, source)
    first, second = _terms(value)
    assert first.name == "python:call_result"
    assert first == second
