"""Authenticated builtin ``hasattr`` remains a boolean operation coordinate."""

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor import BuiltinSemanticCallable, OpaqueOpCallsite
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal


def test_builtin_hasattr_returns_exact_opaque_boolean_coordinate():
    receiver = SymbolicValue(make_var("receiver"))
    member = StringValue("__get__")
    builtin = builtin_name_temporal().value_if_bound("hasattr")

    assert type(builtin) is BuiltinSemanticCallable
    assert builtin.operation == "python.hasattr"
    outcome = builtin.callable_application_with(
        CallableApplication((receiver, member), (), "hasattr-site"), None
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is OpaqueOpCallsite
    assert outcome.value.callee == "hasattr"
    assert outcome.value.arg is receiver
    assert outcome.value.extra_args == (member,)
    assert outcome.value.computed is None
    assert type(outcome.value.truth("truth-site")) is Complete


@pytest.mark.parametrize(
    "arguments, keyword_names",
    [
        ((SymbolicValue(make_var("receiver")),), ()),
        (
            (SymbolicValue(make_var("receiver")), StringValue("member")),
            ("obj", "name"),
        ),
    ],
)
def test_builtin_hasattr_refuses_nonexact_call_shape(arguments, keyword_names):
    builtin = builtin_name_temporal().value_if_bound("hasattr")

    with pytest.raises(ConstructionPanic):
        builtin.callable_application_with(
            CallableApplication(arguments, keyword_names, "hasattr-site"), None
        )
