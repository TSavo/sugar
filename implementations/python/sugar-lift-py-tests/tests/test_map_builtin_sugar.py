from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.sugar.map_builtin_sugar import MapBuiltinSugar


SOURCE = """
def id(x):
    return x

map(id, range(1, 4))
"""


def test_map_builtin_sugar_is_site_born_with_source_locus() -> None:
    module = ast.parse(SOURCE)
    fn = module.body[0]
    expr = module.body[1]
    assert isinstance(fn, ast.FunctionDef)
    assert isinstance(expr, ast.Expr)

    sugar = MapBuiltinSugar.from_site(
        SourceSite.from_node(expr.value, "map_builtin.py"),
        functions_by_name={"id": fn},
        blame="map_builtin.py:5:0",
    )

    assert isinstance(sugar, MapBuiltinSugar)
    assert sugar.source_line == 5
    assert sugar.source_col == 0
    assert not hasattr(sugar, "call")
