from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole


def build_add_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.add_sugar import AddSugar

    sugar = AddSugar.from_site(
        site,
        receiver=ctx.build_body(site.node.func.value, SugarRole.TERM),
        operand=ctx.build_body(site.node.args[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("AddSugar claim built a non-add call")
    return sugar


def build_array_literal_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar

    sugar = ArrayLiteralSugar.from_site(
        site,
        elements=tuple(
            ctx.build_body(element, SugarRole.TERM) for element in site.node.elts
        ),
    )
    if sugar is None:
        raise TypeError("ArrayLiteralSugar claim built a non-array literal")
    return sugar


def build_binop_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar

    sugar = BinOpSugar.from_site(
        site,
        left=ctx.build_body(site.node.left, SugarRole.TERM),
        right=ctx.build_body(site.node.right, SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BinOpSugar claim built a non-addition")
    return sugar


def build_bitwise_op_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.bitwise_op_sugar import BitwiseOpSugar

    sugar = BitwiseOpSugar.from_site(
        site,
        left=ctx.build_body(site.node.left, SugarRole.TERM),
        right=ctx.build_body(site.node.right, SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BitwiseOpSugar claim built a non-bitwise op")
    return sugar


def build_builder_ctor_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.builder_ctor_sugar import BuilderCtorSugar

    sugar = BuilderCtorSugar.from_site(
        site,
        items=ctx.build_body(site.node.args[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BuilderCtorSugar claim built a non-builder call")
    return sugar


def build_lambda_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar

    sugar = LambdaSugar.from_site(
        site,
        body=ctx.build_body(site.node.body, SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("LambdaSugar claim built a non-lambda")
    return sugar


def build_list_literal_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.list_literal_sugar import ListLiteralSugar

    sugar = ListLiteralSugar.from_site(
        site,
        elements=tuple(
            ctx.build_body(element, SugarRole.TERM) for element in site.node.elts
        ),
    )
    if sugar is None:
        raise TypeError("ListLiteralSugar claim built a non-list literal")
    return sugar


def build_map_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.map_sugar import MapSugar

    if not (
        isinstance(site.node, ast.Call)
        and isinstance(site.node.func, ast.Attribute)
        and site.node.func.attr == "map"
        and len(site.node.args) == 1
    ):
        raise TypeError("MapSugar claim built a non-map call")
    sugar = MapSugar.from_site(
        site,
        receiver=ctx.build_body(site.node.func.value, SugarRole.TERM),
        mapper=ctx.build_body(site.node.args[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("MapSugar claim built a non-map call")
    return sugar


def build_to_list_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.to_list_sugar import ToListSugar

    sugar = ToListSugar.from_site(
        site,
        receiver=ctx.build_body(site.node.func.value, SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("ToListSugar claim built a non-to-list call")
    return sugar
