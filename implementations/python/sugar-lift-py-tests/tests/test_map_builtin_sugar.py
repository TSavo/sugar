from __future__ import annotations

import ast

from factory_reduce import array_map_pairs

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.sugar.map_builtin_sugar import MapBuiltinSugar


def _native(call: str, expected: str):
    return array_map_pairs(
        f"def id(x):\n    return x\ndef t():\n    assert {call} == {expected}\n"
    )


def test_map_builtin_applies_the_ref_to_each_element_in_composition():
    # map(id, range(1,4)) composes FunctionRef + Range: id applied pointwise to
    # 1,2,3 -> the conjoined equalities all hold (sat).
    assert all(left == right for left, right in _native("list(map(id, range(1, 4)))", "[1, 2, 3]"))
    # a wrong expected leaves an unequal pair (unsat) -- no false discharge.
    assert any(left != right for left, right in _native("list(map(id, range(1, 4)))", "[1, 2, 99]"))


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
