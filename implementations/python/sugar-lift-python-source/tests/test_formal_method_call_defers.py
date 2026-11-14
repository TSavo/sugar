"""A method call on a formal waits for the caller's actual to select it.

``def f(y): return y.foo()`` stood as the bare ``call:foo(y)`` coordinate and
always completed: whatever the caller passes, the lift claimed the call never
raises.  The receiver's runtime type selects the method, and the caller
supplies it, so the call now defers through ``NativeOperationExitCarrierV1``
with the ``method_call`` operator.  Its projector re-runs the dispatch on the
resolved actual: a floor's method body, the container law (#7603), or the two
faces of a method no floor answers (#7616).  A carrier no caller discharges is
residue, never a completion.

A list/dict/set that reaches a method call by binding (a helper's formal bound
to the caller's actual) is decided by the container law only where the law
reads the operands alone: its contents are not testified as the contents at
this call.  Anything else is two-faced under its ``python:builtin_method``
atom.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    production_native_operation_operators,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ListValue, StringValue, TermValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_unprojected_method_call_faces import _owners, _split


def _carrier(tmp_path, source):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    outcome = func.sugar().desugar()
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "method_call"
    return outcome


def _discharge(carrier, actual):
    (cid, *_rest) = carrier.demand.operand_coordinate_cids
    return carrier.discharge(None, {cid: actual})


def _faces(exits):
    completed = [face.value for face in exits.exits if isinstance(face, Completed)]
    halted = [face.effect for face in exits.exits if isinstance(face, Halted)]
    return completed, halted


def test_method_call_is_an_enrolled_native_operation():
    assert "method_call" in production_native_operation_operators()
    assert "method_call" in _NATIVE_OPERATION_PROJECTORS


def test_a_formal_receiver_is_never_a_completion(tmp_path):
    with pytest.raises(ConstructionPanic, match="undischarged native operation"):
        _split(tmp_path, "def f(y):\n    return y.foo()\n")


def test_a_formal_operand_defers_too(tmp_path):
    carrier = _carrier(tmp_path, "def f(y):\n    return 'a'.index(y)\n")
    assert carrier.demand.operand_coordinate_cids[0] is None
    assert any(carrier.demand.operand_coordinate_cids[3:])


def test_a_str_actual_selects_the_two_faces(tmp_path):
    carrier = _carrier(tmp_path, "def f(y):\n    return y.foo()\n")
    _completed, halted = _faces(_discharge(carrier, StringValue("a")))
    assert _owners(halted) == ["UnknownCallee:foo"]


def test_a_list_actual_selects_the_container_law(tmp_path):
    carrier = _carrier(tmp_path, "def f(y):\n    return y.append(1)\n")
    completed, halted = _faces(_discharge(carrier, ListValue(())))
    (universe,) = completed
    (returned,) = universe.record.statements
    assert returned.value == NoneValue()
    assert halted == []


def test_a_contents_read_is_two_faced(tmp_path):
    # Whether ``pop`` raises reads the contents, which are not testified at
    # a call reached by binding.
    carrier = _carrier(tmp_path, "def f(y):\n    return y.pop()\n")
    _completed, halted = _faces(_discharge(carrier, ListValue((TermValue(5),))))
    assert _owners(halted) == ["BuiltinMethodCall:list.pop"]


def test_keyword_actuals_ride_the_carrier(tmp_path):
    carrier = _carrier(tmp_path, "def f(y):\n    return y.foo(1, k=2)\n")
    _completed, halted = _faces(_discharge(carrier, StringValue("a")))
    assert _owners(halted) == ["UnknownCallee:foo"]


def test_a_helper_pop_on_an_empty_actual_may_raise(tmp_path):
    source = "def g(y):\n    return y.pop()\ndef f():\n    return g([])\n"
    _returns, halts = _split(tmp_path, source)
    assert _owners(halts) == ["BuiltinMethodCall:list.pop"]


def test_a_helper_append_never_raises_and_applies(tmp_path):
    source = (
        "def g(y):\n"
        "    y.append(1)\n"
        "def f():\n"
        "    r = []\n"
        "    g(r)\n"
        "    return r\n"
    )
    returns, halts = _split(tmp_path, source)
    assert returns == [ListValue((TermValue(1),))]
    assert halts == []


def test_a_source_method_on_a_formal_runs_its_body(tmp_path):
    source = (
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
        "def g(y):\n"
        "    return y.m()\n"
        "def f():\n"
        "    return g(C())\n"
    )
    _returns, halts = _split(tmp_path, source)
    assert halts == []
