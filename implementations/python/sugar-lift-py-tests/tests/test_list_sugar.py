from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.sugar.list_sugar import ListSugar


SOURCE = """
def id(x):
    return x

list(map(id, range(1, 4)))
"""


def test_list_sugar_is_site_born_without_raw_call_storage() -> None:
    module = ast.parse(SOURCE)
    fn = module.body[0]
    expr = module.body[1]
    assert isinstance(fn, ast.FunctionDef)
    assert isinstance(expr, ast.Expr)

    sugar = ListSugar.from_site(
        SourceSite.from_node(expr.value, "list_map.py"),
        functions_by_name={"id": fn},
        blame="list_map.py:5:0",
    )

    assert isinstance(sugar, ListSugar)
    assert not hasattr(sugar, "call")
