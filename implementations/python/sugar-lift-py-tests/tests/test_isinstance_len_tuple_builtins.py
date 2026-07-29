"""Builtin isinstance / len / tuple construction for returned-manager factories."""

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor import (
    BuiltinSemanticCallable,
    CallSiteValue,
    ComprehensionValue,
    SliceValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import ctor
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


def test_authenticated_tuple_construct_retains_symbolic_comprehension_sequence():
    temporal = builtin_name_temporal()
    tuple_fn = temporal.value_if_bound("tuple")
    assert isinstance(tuple_fn, BuiltinSemanticCallable)
    source = ComprehensionValue(ctor("py.generator_expression", ()))

    result = tuple_fn.callable_application_with(
        CallableApplication((source,), (), "tuple-call-site"), None
    )

    assert isinstance(result, Complete)
    assert type(result.value).__name__ == "TupleCoordinateValue"
    assert result.value.source is source
    sliced = result.value.subscript(
        SliceValue(None, None, TermValue(2)), "tuple-slice-site"
    )
    assert isinstance(sliced, Complete)
    assert type(sliced.value).__name__ == "TupleCoordinateValue"
    assert sliced.value.source is result.value
    assert sliced.value.index == SliceValue(None, None, TermValue(2))
    assert sliced.value.site == "tuple-slice-site"


def test_shadowed_and_foreign_tuple_targets_do_not_construct_symbolic_tuple():
    from dataclasses import dataclass

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    @dataclass(frozen=True)
    class ValueSugar(Sugar):
        value: object

        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            del ctx
            return Complete(self.value)

    source = ComprehensionValue(ctor("py.generator_expression", ()))
    shadowed_ctx = ReduceContext.root(owner="shadowed-tuple").with_temporal(
        builtin_name_temporal().bind_value("tuple", TermValue(7))
    )
    shadowed = CallSiteSugar(
        "tuple", (ValueSugar(source),), "shadowed-tuple-site"
    ).desugar(shadowed_ctx)
    assert isinstance(shadowed, Complete)
    assert isinstance(shadowed.value, CallSiteValue)

    foreign_ctx = ReduceContext.root(owner="foreign-tuple").with_temporal(
        builtin_name_temporal().bind_value(
            "tuple", BuiltinSemanticCallable("python.set.construct")
        )
    )
    foreign = CallSiteSugar(
        "tuple", (ValueSugar(source),), "foreign-tuple-site"
    ).desugar(foreign_ctx)
    assert isinstance(foreign, Complete)
    assert isinstance(foreign.value, CallSiteValue)


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
