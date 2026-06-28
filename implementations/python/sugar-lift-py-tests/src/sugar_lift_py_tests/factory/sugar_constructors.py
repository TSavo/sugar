from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole

from .source_site import SourceSite


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


def build_base64_body_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.base64_body_sugar import Base64BodySugar

    function = site.node
    if not isinstance(function, ast.FunctionDef):
        raise TypeError("Base64BodySugar claim built a non-function")
    if len(function.args.args) != 1 or len(function.body) != 5:
        raise TypeError("Base64BodySugar claim built a non-base64 body")
    source_name = function.args.args[0].arg
    alphabet = build_alphabet_literal_sugar(
        SourceSite.from_node(function.body[0], site.filename),
        ctx,
    )
    ords = tuple(
        build_ord_sugar(
            SourceSite.from_node(stmt, site.filename),
            ctx,
            source_name=source_name,
        )
        for stmt in function.body[1:4]
    )
    return_sugar = build_bitwise_base64_sugar(
        SourceSite.from_node(function.body[4], site.filename),
        ctx,
    )
    sugar = Base64BodySugar.from_site(
        site,
        alphabet=alphabet,
        ords=ords,
        return_sugar=return_sugar,
    )
    if sugar is None:
        raise TypeError("Base64BodySugar claim built a non-base64 body")
    return sugar


def build_alphabet_literal_sugar(site, _ctx):
    from sugar_lift_py_tests.sugar.alphabet_literal_sugar import AlphabetLiteralSugar

    sugar = AlphabetLiteralSugar.from_site(site)
    if sugar is None:
        raise TypeError("AlphabetLiteralSugar claim built a non-alphabet literal")
    return sugar


def build_ord_sugar(site, _ctx, *, source_name: str):
    from sugar_lift_py_tests.sugar.ord_sugar import OrdSugar

    sugar = OrdSugar.from_site(site, source_name=source_name)
    if sugar is None:
        raise TypeError("OrdSugar claim built a non-ord assignment")
    return sugar


def build_bitwise_base64_sugar(site, _ctx):
    from sugar_lift_py_tests.sugar.bitwise_base64_sugar import BitwiseBase64Sugar

    sugar = BitwiseBase64Sugar.from_site(site)
    if sugar is None:
        raise TypeError("BitwiseBase64Sugar claim built a non-base64 return")
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


def build_function_call_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.function_call_sugar import FunctionCallSugar

    node = site.node
    if not isinstance(node, ast.Call):
        raise TypeError("FunctionCallSugar claim built a non-call")
    if not isinstance(node.func, ast.Name):
        raise TypeError("FunctionCallSugar claim built a non-name call")
    if node.keywords or len(node.args) != 1:
        raise TypeError("FunctionCallSugar claim built a non-unary call")
    functions_by_name = ctx.name_resolver or {}
    function = functions_by_name.get(node.func.id)
    if function is None:
        raise TypeError("FunctionCallSugar claim built an unresolved function call")
    argument = ctx.build_body(node.args[0], SugarRole.TERM)
    body = _function_call_body(function, ctx)
    sugar = FunctionCallSugar.from_site(
        site,
        argument=argument,
        body=body,
    )
    if sugar is None:
        raise TypeError("FunctionCallSugar claim built a non-function call")
    return sugar


def _function_call_body(function: ast.FunctionDef, ctx):
    if len(function.body) == 1:
        body = function.body[0]
        if isinstance(body, ast.Return) and body.value is not None:
            return ctx.build_body(body.value, SugarRole.TERM)
    return build_base64_body_sugar(SourceSite.from_node(function, ctx.filename), ctx)


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
