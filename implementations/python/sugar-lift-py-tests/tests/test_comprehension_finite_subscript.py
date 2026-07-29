from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete


def test_finite_comprehension_subscript_returns_exact_constructed_member():
    selected = StringValue("display.max_rows")
    value = ComprehensionValue(
        ctor("py.listcomp", ()), finite_elements=(selected,)
    )

    outcome = value.subscript(TermValue(0), "keys[0]")

    assert isinstance(outcome, Complete)
    assert outcome.value is selected


def test_comprehension_subscript_does_not_invent_missing_member_or_finiteness():
    opaque = ComprehensionValue(ctor("py.listcomp", ()))
    unresolved = opaque.subscript(TermValue(0), "keys[0]")
    assert isinstance(unresolved, Complete)
    assert isinstance(unresolved.value, CallSiteValue)
    assert unresolved.value.target_name == "py.subscript"
