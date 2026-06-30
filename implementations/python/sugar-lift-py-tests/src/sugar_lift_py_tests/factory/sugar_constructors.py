from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole

from .source_fragment import SourceFragment


def build_add_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.add_sugar import AddSugar

    sugar = AddSugar.from_site(
        site,
        receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
        operand=ctx.build_body(site.call_args()[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("AddSugar claim built a non-add call")
    return sugar


def build_array_literal_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar

    sugar = ArrayLiteralSugar.from_site(
        site,
        elements=tuple(
            ctx.build_body(element, SugarRole.TERM) for element in site.terms()
        ),
    )
    if sugar is None:
        raise TypeError("ArrayLiteralSugar claim built a non-array literal")
    return sugar


def build_binop_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar

    sugar = BinOpSugar.from_site(
        site,
        left=ctx.build_body(site.binop_left(), SugarRole.TERM),
        right=ctx.build_body(site.binop_right(), SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BinOpSugar claim built a non-addition")
    return sugar


def build_bitwise_op_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.bitwise_op_sugar import BitwiseOpSugar

    sugar = BitwiseOpSugar.from_site(
        site,
        left=ctx.build_body(site.binop_left(), SugarRole.TERM),
        right=ctx.build_body(site.binop_right(), SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BitwiseOpSugar claim built a non-bitwise op")
    return sugar


def build_string_subscript_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.string_subscript_sugar import StringSubscriptSugar

    sugar = StringSubscriptSugar.from_site(
        site,
        receiver=ctx.build_body(site.subscript_receiver(), SugarRole.TERM),
        index=ctx.build_body(site.subscript_index(), SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("StringSubscriptSugar claim built a non-subscript")
    return sugar


def build_builder_ctor_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.builder_ctor_sugar import BuilderCtorSugar

    sugar = BuilderCtorSugar.from_site(
        site,
        items=ctx.build_body(site.call_args()[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("BuilderCtorSugar claim built a non-builder call")
    return sugar


def build_lambda_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar

    sugar = LambdaSugar.from_site(
        site,
        body=ctx.build_body(site.lambda_body(), SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("LambdaSugar claim built a non-lambda")
    return sugar


def build_function_call_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.function_call_sugar import FunctionCallSugar

    if site.observed != "Call":
        raise TypeError("FunctionCallSugar claim built a non-call")
    target = site.call_target_name()
    if target is None:
        raise TypeError("FunctionCallSugar claim built a non-name/attribute call")
    if site.call_has_keywords() or site.call_arg_count() != 1:
        raise TypeError("FunctionCallSugar claim built a non-unary call")
    functions_by_name = ctx.name_resolver or {}
    function = functions_by_name.get(target)
    if function is None:
        raise TypeError("FunctionCallSugar claim built an unresolved function call")
    argument = ctx.build_body(site.call_args()[0], SugarRole.TERM)
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


def _lift_cf_return(node, build_ctx, reduce_ctx):
    """A return expression composes through the factory: the catalog builds it and
    the sugars EMIT THE OPERATIONS (`+`, `bvand`, `str.++`, a callsite, ...). The
    lift stays sort-silent -- the SMT compiler derives each variable's canonical
    carrier from the operations it appears in."""
    from sugar_lift_py_tests.outcome import complete_value

    from .literal_call_report import _floor_to_term

    body = build_ctx.build_body(node, SugarRole.TERM)
    value = complete_value(body.reduce(reduce_ctx), owner="control-flow return")
    return _floor_to_term(value)


def _walk_control_flow(stmts, guards, paths, build_ctx, reduce_ctx):
    from sugar_lift_py_tests.ir import not_

    # `fall_through` accumulates the negated guards of prior terminal `if`s on this
    # level: a statement reached after `if cond: return ...` is only live when
    # `not cond` held, so it inherits that guard.
    fall_through = list(guards)
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                raise TypeError("control-flow: bare return")
            term = _lift_cf_return(stmt.value, build_ctx, reduce_ctx)
            paths.append((tuple(fall_through), term))
            return  # statements after a return are unreachable on this path
        if isinstance(stmt, ast.If):
            guard = _cf_guard(stmt.test)
            _walk_control_flow(
                stmt.body, tuple(fall_through) + (guard,), paths, build_ctx, reduce_ctx
            )
            if stmt.orelse:
                _walk_control_flow(
                    stmt.orelse,
                    tuple(fall_through) + (not_(guard),),
                    paths,
                    build_ctx,
                    reduce_ctx,
                )
                return  # both branches handled; no fall-through past an if/else
            fall_through.append(not_(guard))
            continue
        raise TypeError(f"control-flow statement `{type(stmt).__name__}`")


def build_control_flow_body_sugar(site, ctx):
    from dataclasses import replace

    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.control_flow_body_sugar import ControlFlowBodySugar
    from sugar_lift_py_tests.temporal import TemporalContext

    function = site.node
    if not isinstance(function, ast.FunctionDef):
        raise TypeError("ControlFlowBodySugar claim built a non-function")
    if not function.args.args:
        raise TypeError("ControlFlowBodySugar requires at least one parameter")
    # Bind each param to a sort-NEUTRAL symbolic term -- the lift commits to no
    # sort. The return sugars compose operations over these vars; the SMT compiler
    # derives each var's canonical carrier from the operations it appears in.
    temporal = TemporalContext.empty()
    for arg in function.args.args:
        temporal = temporal.bind_value(arg.arg, SymbolicValue(make_var(arg.arg)))
    reduce_ctx = replace(ctx, temporal=temporal)
    # Compose the body as a Block (which absorbs docstrings/comments as Support) and
    # read its return paths -- the same paths the ad-hoc walk produced, now obtained
    # by composition through the factory.
    from sugar_lift_py_tests.factory.block import Block
    from sugar_lift_py_tests.factory.literal_call_report import _floor_to_term
    from sugar_lift_py_tests.floor import EncodedStringValue, GuardedReturn, ReturnValue
    from sugar_lift_py_tests.outcome import complete_value

    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    block_value = complete_value(block.reduce(reduce_ctx), owner="function body")
    stmts = block_value.statements
    # The factory built one child per source statement as the Block composed; carry
    # those composed lines (each a SugarBody with its audit row) so the body's walk is
    # one row per line, read back off the objects.
    statements = block.sugar.statements
    # Encoder body: the Block composed it to a single unguarded EncodedStringValue
    # return -> lower to the existing str.eq-bv-blocks atom (a recognized leaf, not a
    # separate dispatch path).
    if (
        len(stmts) == 1
        and isinstance(stmts[0], ReturnValue)
        and isinstance(stmts[0].value, EncodedStringValue)
    ):
        from sugar_lift_py_tests.sugar.encoder_body_sugar import EncoderBodySugar

        return EncoderBodySugar(
            parameter=function.args.args[0].arg,
            encoded=stmts[0].value,
            statements=statements,
        )
    paths: list = []
    for outcome in stmts:
        if isinstance(outcome, ReturnValue):
            paths.append(((), _floor_to_term(outcome.value)))
        elif isinstance(outcome, GuardedReturn):
            paths.append((tuple(outcome.guards), _floor_to_term(outcome.value)))
        else:
            raise TypeError(
                f"control-flow body: unexpected outcome `{type(outcome).__name__}`"
            )
    if not paths:
        raise TypeError("ControlFlowBodySugar found no return paths")
    return ControlFlowBodySugar(
        parameter=function.args.args[0].arg,
        paths=tuple(paths),
        formals=tuple(a.arg for a in function.args.args),
        statements=statements,
    )


def _function_call_body(function: ast.FunctionDef, ctx):
    if len(function.body) == 1:
        body = function.body[0]
        if isinstance(body, ast.Return) and body.value is not None:
            return ctx.build_body(body.value, SugarRole.TERM)
    # Every multi-statement body composes as one Block: control flow becomes guarded
    # implications, a string encoder becomes str.eq-bv-blocks, docstrings are absorbed.
    # One path -- GenericBodySugar's ad-hoc walk and the dispatch fork are gone.
    return build_control_flow_body_sugar(
        SourceFragment.from_node(function, ctx.filename), ctx
    )


def build_list_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.list_sugar import ListSugar
    from sugar_lift_py_tests.sugar.map_builtin_sugar import map_builtin_sugar

    functions_by_name = ctx.name_resolver or {}
    # Build the inner MapBuiltinSugar from the factory (passing the raw inner node
    # directly -- map_builtin_sugar is the recognised low-level recogniser for it).
    inner_site = site.call_args()[0]
    body = map_builtin_sugar(inner_site.node, functions_by_name, blame=site.blame)
    if body is None:
        raise TypeError("ListSugar claim: inner argument is not a map(...) call")
    sugar = ListSugar.from_site(site, body=body)
    if sugar is None:
        raise TypeError("ListSugar claim built a non-list(map(...)) call")
    return sugar


def build_list_literal_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.list_literal_sugar import ListLiteralSugar

    sugar = ListLiteralSugar.from_site(
        site,
        elements=tuple(
            ctx.build_body(element, SugarRole.TERM) for element in site.terms()
        ),
    )
    if sugar is None:
        raise TypeError("ListLiteralSugar claim built a non-list literal")
    return sugar


def build_return_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar

    if site.observed != "Return":
        raise TypeError("ReturnSugar claim built a non-return")
    value_site = site.return_value()
    if value_site is None:
        raise TypeError("ReturnSugar requires a return value")
    # The factory builds the value expression (TERM) and hands it in.
    return ReturnSugar(value=ctx.build_body(value_site, SugarRole.TERM))


def build_assign_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

    name = site.assign_target_name()
    if name is None:
        raise TypeError("AssignSugar claim built a non-single-name assignment")
    # The factory builds the RHS (TERM) and hands it in.
    return AssignSugar(
        name=name,
        value=ctx.build_body(site.assign_value(), SugarRole.TERM),
    )


def build_if_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.if_sugar import IfSugar

    if site.observed != "If":
        raise TypeError("IfSugar claim built a non-if")
    # The test lifts to a guard Formula; the then/orelse suites are child Blocks the
    # factory builds and hands in. site.statements() yields the Block-wrapped body and
    # (if non-empty) orelse, each as a SourceFragment; build_body accepts SourceFragment directly.
    body_sites = site.statements()
    then_block = ctx.build_body(body_sites[0], SugarRole.STATEMENT)
    else_block = (
        ctx.build_body(body_sites[1], SugarRole.STATEMENT)
        if len(body_sites) > 1
        else None
    )
    return IfSugar(test=_cf_guard(site.if_test().node), then=then_block, else_block=else_block)


def build_block_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

    if site.observed != "Block":
        raise TypeError("BlockSugar claim built a non-block")
    # The factory builds each statement child (by `owns` at the STATEMENT role) and
    # hands the sub-bodies to BlockSugar -- composition, not a walk.
    return BlockSugar(
        statements=tuple(
            ctx.build_body(stmt, SugarRole.STATEMENT) for stmt in site.statements()
        )
    )


def build_map_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.map_sugar import MapSugar, _is_map_call

    if not _is_map_call(site):
        raise TypeError("MapSugar claim built a non-map call")
    sugar = MapSugar.from_site(
        site,
        receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
        mapper=ctx.build_body(site.call_args()[0], SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("MapSugar claim built a non-map call")
    return sugar


def build_to_list_sugar(site, ctx):
    from sugar_lift_py_tests.sugar.to_list_sugar import ToListSugar

    sugar = ToListSugar.from_site(
        site,
        receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
    )
    if sugar is None:
        raise TypeError("ToListSugar claim built a non-to-list call")
    return sugar
