from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceFragment
from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.function_ref_sugar import FunctionRefSugar


SOURCE = """
def id(x):
    return x

id
"""


def test_function_ref_sugar_is_site_born_without_raw_ast_storage() -> None:
    module = ast.parse(SOURCE)
    fn = module.body[0]
    expr = module.body[1]
    assert isinstance(fn, ast.FunctionDef)
    assert isinstance(expr, ast.Expr)

    sugar = FunctionRefSugar.from_site(
        SourceFragment.from_node(expr.value, "functions.py"),
        functions_by_name={"id": fn},
    )

    assert sugar == FunctionRefSugar(name="id", parameter="x", return_name="x")
    assert not hasattr(sugar, "node")
    assert not hasattr(sugar, "function")
    assert complete_value(sugar.desugar(), owner="function ref") == FunctionCallable(
        name="id",
        parameter="x",
        return_name="x",
    )
