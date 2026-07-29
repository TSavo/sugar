"""Builtin isinstance / len / tuple construction for returned-manager factories."""

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor import (
    BuiltinSemanticCallable,
    TupleValue,
)
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal


def test_isinstance_exception_class_vs_tuple_is_false():
    temporal = builtin_name_temporal()
    isinstance_fn = temporal.value_if_bound("isinstance")
    assert isinstance(isinstance_fn, BuiltinSemanticCallable)
    result = isinstance_fn.callable_application_with(
        CallableApplication(
            (temporal.value_if_bound("Exception"), temporal.value_if_bound("tuple")),
            (),
            "site",
        ),
        None,
    )
    assert isinstance(result, Complete)
    assert isinstance(result.value, FalseBoolLiteralSugar)


def test_isinstance_exception_class_vs_type_is_true():
    temporal = builtin_name_temporal()
    isinstance_fn = temporal.value_if_bound("isinstance")
    result = isinstance_fn.callable_application_with(
        CallableApplication(
            (temporal.value_if_bound("Exception"), temporal.value_if_bound("type")),
            (),
            "site",
        ),
        None,
    )
    assert isinstance(result, Complete)
    assert isinstance(result.value, TrueBoolLiteralSugar)


def test_len_of_singleton_tuple_is_one():
    temporal = builtin_name_temporal()
    length = temporal.value_if_bound("len")
    assert isinstance(length, BuiltinSemanticCallable)
    result = length.callable_application_with(
        CallableApplication(
            (TupleValue((temporal.value_if_bound("Exception"),)),),
            (),
            "site",
        ),
        None,
    )
    assert isinstance(result, Complete)
    assert isinstance(result.value, TermValue)
    assert result.value.value == 1


def test_tuple_construct_from_tuple_value_is_identity():
    temporal = builtin_name_temporal()
    tuple_fn = temporal.value_if_bound("tuple")
    assert isinstance(tuple_fn, BuiltinSemanticCallable)
    source = TupleValue((temporal.value_if_bound("ValueError"),))
    result = tuple_fn.callable_application_with(
        CallableApplication((source,), (), "site"), None
    )
    assert isinstance(result, Complete)
    assert isinstance(result.value, TupleValue)
    assert result.value.elements == source.elements


def test_ground_term_value_equality_folds():
    site = "site"
    assert isinstance(
        TermValue(1).equals(TermValue(1), site).value, TrueBoolLiteralSugar
    )
    assert isinstance(
        TermValue(1).equals(TermValue(2), site).value, FalseBoolLiteralSugar
    )


def test_class_object_exposes_dunder_name():
    temporal = builtin_name_temporal()
    exc = temporal.value_if_bound("Exception")
    result = exc.attribute("__name__", "site")
    assert isinstance(result, Complete)
    assert result.value.value == "Exception"
