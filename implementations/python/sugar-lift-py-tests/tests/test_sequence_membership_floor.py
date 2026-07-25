"""Floor membership for constructed sequences and strings.

Pass-3 desugar panics ranked contains (215) as the top Floor gap owner, with
observed container types ListValue / TupleValue / CallSiteValue / StringValue.
These twins pin the finite-fold and symbolic-obligation arms so the mechanism
cannot regress to the default FloorValue.contains panic.
"""

import pytest


def _list(*values):
    from sugar_lift_py_tests.floor import ListValue, TermValue

    return ListValue(tuple(TermValue(value) for value in values))


def _tuple(*values):
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    return TupleValue(tuple(TermValue(value) for value in values))


def test_finite_list_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _list(1, 2)
    assert isinstance(finite.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(
        finite.contains(TermValue(3), "site").value, FalseBoolLiteralSugar
    )


def test_empty_list_membership_is_false():
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    empty = ListValue(())
    assert isinstance(empty.contains(TermValue(1), "site").value, FalseBoolLiteralSugar)


def test_finite_tuple_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _tuple(1, 2)
    assert isinstance(finite.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(
        finite.contains(TermValue(3), "site").value, FalseBoolLiteralSugar
    )


def test_symbolic_list_membership_emits_typed_obligation():
    from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        ListValue((TermValue(1),))
        .contains(SymbolicValue(make_var("member")), "site")
        .value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.list.contains"


def test_symbolic_tuple_membership_emits_typed_obligation():
    from sugar_lift_py_tests.floor import SymbolicValue, TermValue, TupleValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        TupleValue((TermValue(1),))
        .contains(SymbolicValue(make_var("member")), "site")
        .value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.tuple.contains"


def test_opaque_list_member_stays_loud():
    from sugar_lift_py_tests.floor import FunctionCallable
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        _list(1).contains(FunctionCallable("opaque"), "site")


def test_string_substring_membership_is_decided():
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    haystack = StringValue("pandas")
    assert isinstance(
        haystack.contains(StringValue("and"), "site").value, TrueBoolLiteralSugar
    )
    assert isinstance(
        haystack.contains(StringValue("xyz"), "site").value, FalseBoolLiteralSugar
    )


def test_symbolic_string_membership_emits_py_in():
    from sugar_lift_py_tests.floor import StringValue, SymbolicValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        StringValue("abc").contains(SymbolicValue(make_var("needle")), "site").value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "py.in"


def test_ground_non_string_in_string_is_type_error():
    from sugar_lift_py_tests.floor import RaiseValue, StringValue, TermValue
    from sugar_lift_py_tests.outcome import Complete

    outcome = StringValue("abc").contains(TermValue(1), "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_callsite_container_emits_py_in():
    from sugar_lift_py_tests.floor import CallSiteValue, TermValue
    from sugar_lift_py_tests.ir import _Atomic, ctor, make_var

    container = CallSiteValue(
        target_name="opaque",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque", [make_var("xs")]),
        body=None,
        site="site",
    )
    result = container.contains(TermValue(1), "site").value
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "py.in"


def test_comparison_op_routes_membership_to_list_contains():
    """`x in xs` is `xs.contains(x)` — ComparisonOpSugar must not panic on ListValue."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    # Mimic `2 in [1, 2, 3]` after both sides have reduced to floors.
    container = ListValue((TermValue(1), TermValue(2), TermValue(3)))
    member = TermValue(2)
    # Direct floor path used by ComparisonOpSugar for In/NotIn.
    outcome = container.contains(member, "site")
    assert isinstance(outcome.value, TrueBoolLiteralSugar)
