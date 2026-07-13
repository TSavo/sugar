from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import FunctionCallable, ImportAliasValue
from sugar_lift_py_tests.ir import ctor, eq, make_var, num, py_eq, str_const
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import IntSort


def test_sibling_callable_coordinate_passes_scoped_formula() -> None:
    term = FunctionCallable("later").to_term(owner="test")
    formula = formula_from_ir(py_eq(term, term), var_sorts={})

    scoped = ScopedFormula(formula, allowed_vars={})
    assert scoped.formula.free_vars == set()


def test_function_callable_projects_a_named_constant_not_a_variable() -> None:
    term = FunctionCallable("later").to_term(owner="test")
    assert term == ctor("python:function", [str_const("later")])
    assert term != make_var("later")


def test_import_alias_is_already_a_named_constant_coordinate() -> None:
    term = ImportAliasValue("datetime", "dt").to_term(owner="test")
    assert term == ctor("python:import_alias", [str_const("dt"), str_const("datetime")])


def test_actually_undeclared_variable_still_refuses_scope() -> None:
    formula = formula_from_ir(
        eq(make_var("ghost"), num(1)), var_sorts={"ghost": IntSort()}
    )
    with pytest.raises(FactoryPanic, match="illegal free var.*ghost"):
        ScopedFormula(formula, allowed_vars={})
