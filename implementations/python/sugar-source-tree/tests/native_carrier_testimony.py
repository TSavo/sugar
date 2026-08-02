"""Test doors for the deliberately non-projectable native-operation carrier."""

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet


def completed_function_value(function):
    """Project only an outcome that really completed; never accept a carrier."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, Complete), outcome
    return outcome.value


def native_carrier_for(function, *, operator):
    """Pin the pending operation and prove that it has no value projection."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, NativeOperationExitCarrierV1), outcome
    with pytest.raises(AttributeError, match="value"):
        _ = outcome.value
    assert outcome.demand.operator == operator
    return outcome


def authenticated_function_value(function, *, operator, actuals=None):
    """Complete through the function's own source-frame binder testimony."""
    carrier = native_carrier_for(function, operator=operator)
    frame = function.source_visible_call_frame()
    if actuals is None:
        actuals = tuple(SymbolicValue(make_var(name)) for name in frame.parameters)
    bound = frame.bind_actuals(tuple(actuals), ())
    projected = bound.project_native_carrier(carrier)
    assert isinstance(projected, ExitSet), projected
    completed = tuple(
        exit_ for exit_ in projected.exits if isinstance(exit_, Completed)
    )
    assert len(completed) == 1, projected.exits
    return completed[0].value
