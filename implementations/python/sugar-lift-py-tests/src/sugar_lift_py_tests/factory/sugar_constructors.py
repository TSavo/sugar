from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole

from .source_fragment import SourceFragment


def _cf_operand(frag: SourceFragment):
    from sugar_lift_py_tests.ir import make_var, num, str_const

    if frag.observed == "Name":
        return make_var(frag.name_id())
    if frag.observed == "PrimitiveLiteral" and not isinstance(
        frag.literal_value(), bool
    ):
        val = frag.literal_value()
        if isinstance(val, int):
            return num(val)
        if isinstance(val, str):
            return str_const(val)
    raise TypeError(f"control-flow operand shape `{frag.observed}`")


def _cf_guard(frag: SourceFragment):
    from sugar_lift_py_tests.ir import eq, gt, lt, ne

    if (
        frag.observed == "Compare"
        and len(frag.compare_ops()) == 1
        and len(frag.compare_comparators()) == 1
    ):
        left = _cf_operand(frag.compare_left())
        right = _cf_operand(frag.compare_comparators()[0])
        op_name = frag.compare_ops()[0]
        if op_name == "Eq":
            return eq(left, right)
        if op_name == "NotEq":
            return ne(left, right)
        if op_name == "Gt":
            return gt(left, right)
        if op_name == "Lt":
            return lt(left, right)
    raise TypeError(f"control-flow guard shape `{frag.observed}`")


def _lift_cf_return(node, build_ctx, reduce_ctx):
    """A return expression composes through the factory: the catalog builds it and
    the sugars EMIT THE OPERATIONS (`+`, `bvand`, `str.++`, a callsite, ...). The
    lift stays sort-silent -- the SMT compiler derives each variable's canonical
    carrier from the operations it appears in."""
    from sugar_lift_py_tests.outcome import complete_value
    from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

    body = build_ctx.build_body(node, SugarRole.TERM)
    value = complete_value(body.reduce(reduce_ctx), owner="control-flow return")
    return floor_to_term(value, owner="control-flow return")


def _walk_control_flow(stmts, guards, paths, build_ctx, reduce_ctx):
    from sugar_lift_py_tests.ir import not_

    fall_through = list(guards)
    for stmt in stmts:
        if stmt.observed == "Return":
            if stmt.return_value() is None:
                raise TypeError("control-flow: bare return")
            term = _lift_cf_return(stmt.return_value(), build_ctx, reduce_ctx)
            paths.append((tuple(fall_through), term))
            return
        if stmt.observed == "If":
            guard = _cf_guard(stmt.if_test())
            _walk_control_flow(
                stmt.if_body(),
                tuple(fall_through) + (guard,),
                paths,
                build_ctx,
                reduce_ctx,
            )
            if stmt.if_orelse():
                _walk_control_flow(
                    stmt.if_orelse(),
                    tuple(fall_through) + (not_(guard),),
                    paths,
                    build_ctx,
                    reduce_ctx,
                )
                return
            fall_through.append(not_(guard))
            continue
        raise TypeError(f"control-flow statement `{stmt.observed}`")


def build_control_flow_body_sugar(site, ctx):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.control_flow_body_sugar import ControlFlowBodySugar
    from sugar_lift_py_tests.temporal import TemporalContext, bind_temporal

    if site.observed != "FunctionDef":
        raise TypeError("ControlFlowBodySugar claim built a non-function")
    params = site.function_params()
    if not params:
        raise TypeError("ControlFlowBodySugar requires at least one parameter")
    reduce_ctx = ctx.with_temporal(TemporalContext.empty())
    for param_name in params:
        reduce_ctx = bind_temporal(
            reduce_ctx,
            param_name,
            SymbolicValue(make_var(param_name)),
            owner="sugar_constructors.control_flow_body",
            blame=site.blame,
        )
    from sugar_lift_py_tests.factory.block import Block
    from sugar_lift_py_tests.floor import EncodedStringValue, GuardedReturn, ReturnValue
    from sugar_lift_py_tests.outcome import complete_value
    from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

    body = site.node.body
    block = ctx.build_body(Block.of(body), SugarRole.STATEMENT)
    block_value = complete_value(block.reduce(reduce_ctx), owner="function body")
    stmts = block_value.statements
    statements = block.sugar.statements
    if (
        len(stmts) == 1
        and isinstance(stmts[0], ReturnValue)
        and isinstance(stmts[0].value, EncodedStringValue)
    ):
        from sugar_lift_py_tests.sugar.encoder_body_sugar import EncoderBodySugar

        return EncoderBodySugar(
            parameter=params[0],
            encoded=stmts[0].value,
            statements=statements,
        )
    paths: list = []
    for outcome in stmts:
        if isinstance(outcome, ReturnValue):
            paths.append(((), floor_to_term(outcome.value, owner="control-flow body")))
        elif isinstance(outcome, GuardedReturn):
            paths.append(
                (
                    tuple(outcome.guards),
                    floor_to_term(outcome.value, owner="control-flow body"),
                )
            )
        else:
            raise TypeError(
                f"control-flow body: unexpected outcome `{type(outcome).__name__}`"
            )
    if not paths:
        raise TypeError("ControlFlowBodySugar found no return paths")
    return ControlFlowBodySugar(
        parameter=params[0],
        paths=tuple(paths),
        formals=tuple(params),
        statements=statements,
    )


def build_bridge_body(site: SourceFragment, ctx):
    body_frags = site.function_body()
    if len(body_frags) == 1:
        body_frag = body_frags[0]
        if body_frag.observed == "Return" and body_frag.return_value() is not None:
            return ctx.build_body(body_frag.return_value(), SugarRole.TERM)
    return build_control_flow_body_sugar(site, ctx)
