from frame_fresh import fresh


def _numbers(*values):
    from sugar_lift_py_tests.floor import SetValue, TermValue

    return fresh(SetValue, tuple(TermValue(value) for value in values))


def _values(result):
    return tuple(item.value for item in result.completed_value().elements)


def test_finite_set_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _numbers(1, 2)
    assert isinstance(
        finite.contains(TermValue(2), "site").completed_value(), TrueBoolLiteralSugar
    )
    assert isinstance(
        finite.contains(TermValue(3), "site").completed_value(), FalseBoolLiteralSugar
    )


def test_finite_set_union_intersection_and_difference_are_closed():
    assert _values(_numbers(1, 2).bitwise_or(_numbers(2, 3), "site", None)) == (1, 2, 3)
    assert _values(_numbers(1, 2).bitwise_and(_numbers(2, 3), "site", None)) == (2,)
    assert _values(_numbers(1, 2).subtract(_numbers(2, 3), "site", None)) == (1,)


def test_symbolic_finite_membership_is_the_undecided_membership():
    """``x in {1}`` hashes ``x`` and may run ``type(x).__eq__``: the
    undecided membership, two-faced (#7757 H10)."""
    from sugar_lift_py_tests.floor import SetValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import make_var
    from test_membership_undecided_and_identity_twins_7757 import (
        assert_undecided_membership,
    )

    assert_undecided_membership(
        fresh(SetValue, (TermValue(1),)).contains(
            SymbolicValue(make_var("member")), "site"
        )
    )


def test_a_function_needle_in_a_set_is_never_a_panic():
    """``f in {1}`` hashes ``f``: a member like any object, never a
    construction panic (#7757 H11)."""
    from sugar_lift_py_tests.floor import LambdaCallable
    from test_membership_undecided_and_identity_twins_7757 import (
        assert_undecided_membership,
    )

    opaque = LambdaCallable(parameters=(), body=None, construction_identity="opaque")
    assert_undecided_membership(_numbers(1).contains(opaque, "site"))


def test_authenticated_set_constructor_closes_finite_dict_keys():
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    receiver = builtin_name_temporal().value_for("set")
    source = fresh(DictValue, ((StringValue("kept"), TermValue(1)),))

    result = receiver.callable_application_with(
        CallableApplication((source,), (), "site"), None
    )

    assert tuple(item.value for item in result.completed_value().elements) == (
        "kept",
    )
