import pytest


def _numbers(*values):
    from sugar_lift_py_tests.floor import SetValue, TermValue

    return SetValue(tuple(TermValue(value) for value in values))


def _values(result):
    return tuple(item.value for item in result.value.elements)


def test_finite_set_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _numbers(1, 2)
    assert isinstance(finite.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(finite.contains(TermValue(3), "site").value, FalseBoolLiteralSugar)


def test_finite_set_union_intersection_and_difference_are_closed():
    assert _values(_numbers(1, 2).bitwise_or(_numbers(2, 3), "site")) == (1, 2, 3)
    assert _values(_numbers(1, 2).bitwise_and(_numbers(2, 3), "site")) == (2,)
    assert _values(_numbers(1, 2).subtract(_numbers(2, 3), "site")) == (1,)


def test_symbolic_finite_membership_emits_typed_obligation():
    from sugar_lift_py_tests.floor import SetValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = SetValue((TermValue(1),)).contains(
        SymbolicValue(make_var("member")), "site"
    ).value
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.set.contains"


def test_opaque_member_stays_loud():
    from sugar_lift_py_tests.floor import FunctionCallable
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        _numbers(1).contains(FunctionCallable("opaque"), "site")


def test_authenticated_set_constructor_closes_finite_dict_keys():
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    receiver = builtin_name_temporal().value_for("set")
    source = DictValue(((StringValue("kept"), TermValue(1)),))

    result = receiver.callable_application_with(
        CallableApplication((source,), (), "site"), None
    )

    assert tuple(item.value for item in result.value.elements) == ("kept",)
