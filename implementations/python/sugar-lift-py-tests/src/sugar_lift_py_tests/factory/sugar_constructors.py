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


def build_string_subscript_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.string_subscript_sugar import StringSubscriptSugar

    index_node = site.node.slice
    if isinstance(index_node, ast.Index):  # py<3.9 compatibility
        index_node = index_node.value
    sugar = StringSubscriptSugar.from_site(
        site,
        receiver=ctx.build_body(site.node.value, SugarRole.TERM),
        index=ctx.build_body(index_node, SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("StringSubscriptSugar claim built a non-subscript")
    return sugar


def build_generic_body_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.generic_body_sugar import GenericBodySugar
    from sugar_lift_py_tests.sugar.ord_sugar import OrdSugar
    from sugar_lift_py_tests.sugar.string_literal_sugar import string_literal_sugar

    function = site.node
    if not isinstance(function, ast.FunctionDef):
        raise TypeError("GenericBodySugar claim built a non-function")
    if not function.args.args:
        raise TypeError("GenericBodySugar requires at least one parameter")
    # The lifted value binds to the first positional parameter; any others carry
    # their own defaults (e.g. rot90's k, axes) and are not part of the value.
    parameter = function.args.args[0].arg
    if len(function.body) < 2:
        raise TypeError("GenericBodySugar requires assignments and a return")
    *assign_stmts, ret = function.body
    if not isinstance(ret, ast.Return) or ret.value is None:
        raise TypeError("GenericBodySugar requires a return statement")
    table_name: str | None = None
    table_value: str | None = None
    ord_bytes: list[tuple[int, str]] = []
    assign_kinds: list[str] = []
    for stmt in assign_stmts:
        if (
            not isinstance(stmt, ast.Assign)
            or len(stmt.targets) != 1
            or not isinstance(stmt.targets[0], ast.Name)
        ):
            raise TypeError("GenericBodySugar assignment must bind a single name")
        ord_sugar = OrdSugar.from_site(
            SourceSite.from_node(stmt, ctx.filename), source_name=parameter
        )
        if ord_sugar is not None:
            ord_bytes.append((ord_sugar.index, ord_sugar.target))
            assign_kinds.append("ord")
            continue
        literal = string_literal_sugar(stmt.value)
        if literal is not None:
            if table_name is not None:
                raise TypeError("GenericBodySugar expects a single table literal")
            table_name = stmt.targets[0].id
            table_value = literal.value
            assign_kinds.append("table")
            continue
        raise TypeError("GenericBodySugar assignment is neither a table literal nor an ord byte")
    if table_name is None or not ord_bytes:
        raise TypeError("GenericBodySugar needs a table literal and at least one ord byte")
    byte_names = tuple(target for _, target in sorted(ord_bytes, key=lambda pair: pair[0]))
    return_body = ctx.build_body(ret.value, SugarRole.TERM)
    return GenericBodySugar(
        parameter=parameter,
        table_name=table_name,
        table_value=table_value,
        byte_names=byte_names,
        assign_kinds=tuple(assign_kinds),
        return_body=return_body,
        build_ctx=ctx,
    )


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
    from sugar_lift_py_tests.sugar.function_call_sugar import (
        FunctionCallSugar,
        callee_target,
    )

    node = site.node
    if not isinstance(node, ast.Call):
        raise TypeError("FunctionCallSugar claim built a non-call")
    target = callee_target(node)
    if target is None:
        raise TypeError("FunctionCallSugar claim built a non-name/attribute call")
    if node.keywords or len(node.args) != 1:
        raise TypeError("FunctionCallSugar claim built a non-unary call")
    functions_by_name = ctx.name_resolver or {}
    function = functions_by_name.get(target)
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


def _cf_operand(node):
    from sugar_lift_py_tests.ir import make_var, num, str_const

    if isinstance(node, ast.Name):
        return make_var(node.id)
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        if isinstance(node.value, int):
            return num(node.value)
        if isinstance(node.value, str):
            return str_const(node.value)
    raise TypeError(f"control-flow operand shape `{type(node).__name__}`")


def _cf_guard(test):
    from sugar_lift_py_tests.ir import eq, gt, lt, ne

    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        left = _cf_operand(test.left)
        right = _cf_operand(test.comparators[0])
        op = test.ops[0]
        if isinstance(op, ast.Eq):
            return eq(left, right)
        if isinstance(op, ast.NotEq):
            return ne(left, right)
        if isinstance(op, ast.Gt):
            return gt(left, right)
        if isinstance(op, ast.Lt):
            return lt(left, right)
    raise TypeError(f"control-flow guard shape `{type(test).__name__}`")


def _walk_control_flow(stmts, guards, paths):
    from sugar_lift_py_tests.ir import not_

    # `fall_through` accumulates the negated guards of prior terminal `if`s on this
    # level: a statement reached after `if cond: return ...` is only live when
    # `not cond` held, so it inherits that guard.
    fall_through = list(guards)
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                raise TypeError("control-flow: bare return")
            paths.append((tuple(fall_through), _cf_operand(stmt.value)))
            return  # statements after a return are unreachable on this path
        if isinstance(stmt, ast.If):
            guard = _cf_guard(stmt.test)
            _walk_control_flow(stmt.body, tuple(fall_through) + (guard,), paths)
            if stmt.orelse:
                _walk_control_flow(stmt.orelse, tuple(fall_through) + (not_(guard),), paths)
                return  # both branches handled; no fall-through past an if/else
            fall_through.append(not_(guard))
            continue
        raise TypeError(f"control-flow statement `{type(stmt).__name__}`")


def build_control_flow_body_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.control_flow_body_sugar import ControlFlowBodySugar

    function = site.node
    if not isinstance(function, ast.FunctionDef):
        raise TypeError("ControlFlowBodySugar claim built a non-function")
    if not function.args.args:
        raise TypeError("ControlFlowBodySugar requires at least one parameter")
    paths: list = []
    _walk_control_flow(function.body, (), paths)
    if not paths:
        raise TypeError("ControlFlowBodySugar found no return paths")
    return ControlFlowBodySugar(
        parameter=function.args.args[0].arg,
        paths=tuple(paths),
        formals=tuple(a.arg for a in function.args.args),
        statement_count=len(function.body),
    )


def _function_call_body(function: ast.FunctionDef, ctx):
    if len(function.body) == 1:
        body = function.body[0]
        if isinstance(body, ast.Return) and body.value is not None:
            return ctx.build_body(body.value, SugarRole.TERM)
    if any(isinstance(stmt, ast.If) for stmt in function.body):
        return build_control_flow_body_sugar(
            SourceSite.from_node(function, ctx.filename), ctx
        )
    return build_generic_body_sugar(SourceSite.from_node(function, ctx.filename), ctx)


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
