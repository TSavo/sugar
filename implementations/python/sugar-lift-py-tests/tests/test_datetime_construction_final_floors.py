from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    BoundVar,
    CallSiteValue,
    GuardedValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def test_string_add_folds_strings_and_cites_opaque_peer() -> None:
    assert StringValue("left").add(StringValue("right"), "t.py:1") == Complete(
        StringValue("leftright")
    )
    opaque = CallSiteValue("fragment", (), (), ctor("call:fragment", []), None)
    assert StringValue("left").add(opaque, "t.py:1").value.to_term(owner="test") == ctor(
        "+", [str_const("left"), ctor("call:fragment", [])]
    )


def test_numeric_add_cites_imported_opaque_peer() -> None:
    opaque = SymbolicValue(make_var("opaque"))
    assert TermValue(4).add(opaque, "t.py:1").value.to_term(owner="test") == ctor(
        "+", [num(4), make_var("opaque")]
    )
    assert TermValue(4).add(TrueBoolLiteralSugar(site="t.py:1"), "t.py:1") == Complete(
        TermValue(5)
    )


def test_guarded_arithmetic_distributes_over_both_faces() -> None:
    guard = atomic("choose", [])
    value = GuardedValue(guard, TermValue(7), TermValue(8))
    assert value.modulo(TermValue(3), "t.py:1") == Complete(
        GuardedValue(guard, TermValue(1), TermValue(2))
    )
    assert value.floor_divide(TermValue(3), "t.py:1") == Complete(
        GuardedValue(guard, TermValue(2), TermValue(2))
    )


def test_bound_var_projects_by_recomposing_its_cited_source() -> None:
    body = SugarBody(
        build_node(ast.parse("5", mode="eval").body, filename="t.py", role=SugarRole.TERM).sugar,
        SugarRole.TERM,
    )
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    assert BoundVar("x", body, scope=ctx).to_term(owner="test") == num(5)


def test_builtin_call_result_method_chain_uses_linear_owner() -> None:
    for expression in ("type(self).fromordinal(o)", "super().__new__(cls)"):
        sugar = build_node(
            ast.parse(expression, mode="eval").body,
            filename="t.py",
            role=SugarRole.TERM,
        ).sugar
        assert type(sugar).__name__ == "MethodChainSugar"


def test_break_is_owned_without_source_ancestor_reconstruction() -> None:
    sugar = build_node(ast.Break(), filename="t.py", role=SugarRole.STATEMENT).sugar
    assert type(sugar).__name__ == "BreakSugar"
