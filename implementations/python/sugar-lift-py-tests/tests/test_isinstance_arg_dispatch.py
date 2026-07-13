from __future__ import annotations

import pytest

import ast

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.effect import CallResultTypeRuntimeEffect
from sugar_lift_py_tests.factory import default_catalog
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ImportAliasValue,
    PredicateValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, or_, str_const
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.temporal import TemporalContext


def _tester(value_term, type_term):
    return atomic("adt.is_python_type", [value_term, type_term])


def test_imported_type_name_emits_native_tester_atom() -> None:
    value = reduce_value(
        "isinstance(x, ImportedType)",
        {
            "x": SymbolicValue(make_var("x")),
            "ImportedType": ImportAliasValue("SomeType", "ImportedType"),
        },
    )

    assert value == PredicateValue(
        _tester(
            make_var("x"),
            ctor("python:type", [str_const("SomeType")]),
        )
    )
    assert "call:isinstance" not in repr(value)


def test_builtin_type_call_emits_native_tester_atom() -> None:
    value = reduce_value(
        "isinstance(x, type(y))",
        {
            "x": SymbolicValue(make_var("x")),
            "y": SymbolicValue(make_var("y")),
        },
    )

    assert isinstance(value, PredicateValue)
    assert value.formula == _tester(make_var("x"), ctor("call:type", [make_var("y")]))
    assert "call:isinstance" not in repr(value)


def test_tuple_of_citable_types_is_native_tester_disjunction() -> None:
    value = reduce_value(
        "isinstance(x, (ImportedType, int))",
        {
            "x": SymbolicValue(make_var("x")),
            "ImportedType": ImportAliasValue("SomeType", "ImportedType"),
        },
    )

    assert isinstance(value, PredicateValue)
    assert value.formula == or_(
        [
            _tester(make_var("x"), ctor("python:type", [str_const("SomeType")])),
            _tester(make_var("x"), ctor("python:type", [str_const("int")])),
        ]
    )
    assert "call:isinstance" not in repr(value)


def test_known_contract_call_result_emits_native_tester_atom() -> None:
    type_coordinate = ctor("python:type", [str_const("Widget")])
    callsite = CallSiteValue(
        target_name="type_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:type_factory", []),
        body=None,
        python_type_coordinate=type_coordinate,
    )

    outcome = callsite.test_python_type(SymbolicValue(make_var("x")), None)

    assert isinstance(outcome, Complete)
    assert outcome.value.formula == _tester(make_var("x"), type_coordinate)
    assert "call:isinstance" not in repr(outcome.value)


def test_arbitrary_call_result_type_is_a_named_runtime_effect() -> None:
    node = ast.parse("isinstance(x, factory())", mode="eval").body
    temporal = TemporalContext.empty().bind_value("x", SymbolicValue(make_var("x")))
    ctx = FactoryBuildContext(
        filename="t.py", catalog=default_catalog(), temporal=temporal
    )

    outcome = ctx.build_body(node, SugarRole.TERM).reduce(ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, CallResultTypeRuntimeEffect)
    assert "factory" in outcome.reason


def test_tuple_with_uncitable_element_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="identified python:type coordinate"):
        reduce_value(
            "isinstance(x, (int, unknown_type))",
            {
                "x": SymbolicValue(make_var("x")),
                "unknown_type": SymbolicValue(make_var("unknown_type")),
            },
        )


def test_dispatch_receivers_declare_explicit_type_tester_arms() -> None:
    from sugar_lift_py_tests.floor import TupleValue

    assert "test_python_type" in ImportAliasValue.__dict__
    assert "test_python_type" in CallSiteValue.__dict__
    assert "python_type_coordinate" in CallSiteValue.__dataclass_fields__
    assert "test_python_type" in TupleValue.__dict__
