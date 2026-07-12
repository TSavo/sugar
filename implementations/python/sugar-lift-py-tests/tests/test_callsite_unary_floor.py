from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import _Ctor, ctor
from sugar_lift_py_tests.outcome import Complete


def test_callsite_unary_minus_cites_the_existing_call_coordinate() -> None:
    value = CallSiteValue(
        target_name="timedelta",
        arg_values=(TermValue(1),),
        parameters=(),
        term=ctor("call:timedelta", [TermValue(1).to_term(owner="test")]),
        body=None,
        site="datetime.py:510:12",
    )

    outcome = value.unary_minus("datetime.py:510:11")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    term = outcome.value.to_term(owner="test")
    assert isinstance(term, _Ctor)
    assert term.name == "py.neg"
    assert term.args == (value.term,)
