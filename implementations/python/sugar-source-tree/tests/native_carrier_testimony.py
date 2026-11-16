"""Test doors for the deliberately non-projectable native-operation carrier."""

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.outcome import ExitSet


def completed_function_value(function):
    """Project only an outcome that really completed; never accept a carrier."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    assert value is not None, outcome
    return value


def native_carrier_for(function, *, operator):
    """Pin the pending operation and prove that it has no value projection."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, NativeOperationExitCarrierV1), outcome
    with pytest.raises(AttributeError, match="value"):
        _ = outcome.value
    assert outcome.demand.operator == operator
    return outcome

