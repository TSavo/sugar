from __future__ import annotations

import ast

from factory_reduce import array_map_pairs

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.sugar.list_sugar import ListSugar
from sugar_lift_py_tests.sugar.map_builtin_sugar import map_builtin_sugar


def test_list_collects_the_map_into_the_asserted_sequence():
    # list(map(id, range(2, 6))) collects the mapped range into [2,3,4,5]; the
    # composed equalities hold (sat), and a wrong expected discriminates (unsat).
    def native(expected):
        return array_map_pairs(
            "def id(x):\n    return x\n"
            f"def t():\n    assert list(map(id, range(2, 6))) == {expected}\n"
        )

    assert all(left == right for left, right in native("[2, 3, 4, 5]"))
    assert any(left != right for left, right in native("[2, 3, 4, 99]"))


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

    blame = "list_map.py:5:0"
    outer_site = SourceSite.from_node(expr.value, "list_map.py")
    # The body (inner map(...)) is built by the factory before constructing ListSugar.
    inner_site = outer_site.call_args()[0]
    body = map_builtin_sugar(inner_site, {"id": fn}, blame=blame)
    assert body is not None
    sugar = ListSugar.from_site(outer_site, body=body)

    assert isinstance(sugar, ListSugar)
    assert not hasattr(sugar, "call")
