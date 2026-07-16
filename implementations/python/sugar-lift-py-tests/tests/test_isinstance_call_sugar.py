"""Vendor ``isinstance(value, type)`` lifts as a reserved tester predicate."""

from __future__ import annotations

import ast

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var, str_const
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _selected(expr: str) -> str:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(expr, mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    return result.audit_row.selected


def test_ground_isinstance_folds_true_and_false_faces() -> None:
    assert type(reduce_value("isinstance('vendor', str)")) is TrueBoolLiteralSugar
    assert type(reduce_value("isinstance('vendor', int)")) is FalseBoolLiteralSugar


def test_symbolic_isinstance_emits_reserved_tester_with_type_coordinate() -> None:
    value = reduce_value(
        "isinstance(x, str)", binds={"x": SymbolicValue(make_var("x"))}
    )
    assert type(value) is PredicateValue
    assert value.formula == atomic(
        "adt.is_python_type",
        [make_var("x"), ctor("python:type", [str_const("str")])],
    )


def test_symbolic_isinstance_carries_type_and_never_uses_call_euf() -> None:
    str_predicate = reduce_value(
        "isinstance(x, str)", binds={"x": SymbolicValue(make_var("x"))}
    )
    int_predicate = reduce_value(
        "isinstance(x, int)", binds={"x": SymbolicValue(make_var("x"))}
    )
    assert type(str_predicate) is PredicateValue
    assert type(int_predicate) is PredicateValue
    assert str_predicate.formula != int_predicate.formula
    assert str_predicate.formula.name.startswith("adt.is_")
    assert "call:isinstance" not in repr(str_predicate.formula)
    assert "call:isinstance" not in repr(int_predicate.formula)


def test_ownership_partition_is_exact() -> None:
    assert _selected("isinstance(x, str)") == "IsinstanceCallSugar"
    assert _selected("isinstance(x)") == "CallSugar"
    assert _selected("isinstance(x, class_or_tuple=str)") == "KeywordCallSugar"
    assert _selected("f(x)") == "CallSugar"


def test_non_owned_calls_keep_call_sugar_coordinate() -> None:
    value = reduce_value("f(x)", binds={"x": SymbolicValue(make_var("x"))})
    assert type(value) is CallSiteValue
    assert value.term == ctor("call:f", [make_var("x")])


def test_witness_pair_discriminates_on_isinstance_face() -> None:
    from sugar_lift_py_tests.sugar.isinstance_call_sugar import IsinstanceCallSugar

    witness = IsinstanceCallSugar.witnesses()
    assert witness.owner_sugar == "IsinstanceCallSugar"
    assert "return isinstance(1, int)" in witness.truthful.source
    assert "assert A(5) == True" in witness.truthful.source
    assert "assert A(5) == False" in witness.lying.source
    assert witness.truthful.expected == "sat"
    assert witness.lying.expected == "unsat"
