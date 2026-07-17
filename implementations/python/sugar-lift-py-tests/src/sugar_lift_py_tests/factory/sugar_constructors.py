from __future__ import annotations

from typing import cast

from sugar_lift_py_tests.claim import SugarRole

from .source_fragment import SourceFragment


class IncompleteFunctionBody(Exception):
    def __init__(self, incomplete):
        super().__init__(incomplete.reason)
        self.incomplete = incomplete


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
    from sugar_lift_py_tests.outcome import Incomplete, complete_value
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
    from sugar_lift_py_tests.sugar.control_flow_body_sugar import ControlFlowBodySugar

    if site.observed != "FunctionDef":
        raise TypeError("ControlFlowBodySugar claim built a non-function")
    params = site.function_params()
    # Zero-parameter bodies are legal dig targets (`def A(): return len([...])`).
    # Formals may be empty; only EncoderBodySugar still needs a named parameter.
    # Formal binds on the BUILD ctx: see `_ctx_with_formal_binds` (Batch A / formal
    # method body dig).
    body_ctx = _ctx_with_formal_binds(site, ctx)
    from sugar_lift_py_tests.factory.block import Block
    from sugar_lift_py_tests.floor import (
        BlockValue,
        EncodedStringValue,
        GuardedReturn,
        ReturnValue,
    )
    from sugar_lift_py_tests.outcome import Incomplete, complete_value
    from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

    body = site.node.body
    block = body_ctx.build_body(Block.of(body), SugarRole.STATEMENT)
    block_outcome = block.reduce(body_ctx)
    if isinstance(block_outcome, Incomplete):
        raise IncompleteFunctionBody(block_outcome)
    block_value = complete_value(block_outcome, owner="function body")
    if type(block_value) is not BlockValue:
        raise TypeError(
            f"ControlFlowBodySugar expected BlockValue, got {type(block_value).__name__}"
        )
    block_value = cast(BlockValue, block_value)
    stmts = block_value.statements
    statements = block.sugar.statements
    if (
        len(stmts) == 1
        and isinstance(stmts[0], ReturnValue)
        and isinstance(stmts[0].value, EncodedStringValue)
    ):
        from sugar_lift_py_tests.sugar.encoder_body_sugar import EncoderBodySugar

        if not params:
            raise TypeError("EncoderBodySugar requires at least one parameter")
        return EncoderBodySugar(
            parameter=params[0],
            encoded=stmts[0].value,
            statements=statements,
        )
    paths: list = []
    opaque_returns: list = []
    from sugar_lift_py_tests.floor import OpaqueOpCallsite

    for outcome in stmts:
        if isinstance(outcome, ReturnValue):
            ret_value = outcome.value
            paths.append(((), floor_to_term(ret_value, owner="control-flow body")))
            # Foldable (computed is not None) AND opaque (computed is None) both
            # belong on opaque_returns: the path post is always
            # `out == call:<op>(...)`; companions are minted only for counted
            # returns (see _opaque_op_companion_facts). Dropping opaque used to
            # leave hash/str-of-symbolic body digs with no coordinate at all.
            if isinstance(ret_value, OpaqueOpCallsite):
                opaque_returns.append(ret_value)
        elif isinstance(outcome, GuardedReturn):
            ret_value = outcome.value
            paths.append(
                (
                    tuple(outcome.guards),
                    floor_to_term(ret_value, owner="control-flow body"),
                )
            )
            if isinstance(ret_value, OpaqueOpCallsite):
                opaque_returns.append(ret_value)
        else:
            raise TypeError(
                f"control-flow body: unexpected outcome `{type(outcome).__name__}`"
            )
    if not paths:
        raise TypeError("ControlFlowBodySugar found no return paths")
    return ControlFlowBodySugar(
        parameter=params[0] if params else "",
        paths=tuple(paths),
        formals=tuple(params),
        statements=statements,
        opaque_returns=tuple(opaque_returns),
    )


def _ctx_with_formal_binds(site: SourceFragment, ctx):
    """Factory build ctx with formals bound as SymbolicValue(<name>).

    CallSugar selects MethodCallStrategy for bare Name receivers only when the
    name is temporally bound at *build* time (`_method_receiver_is_temporally_bound`).
    Universe dig already binds via `build_control_flow_body_sugar`; the single-return
    bridge shortcut must bind too, or `def A(s): return s.mean()` builds as
    factory_panic(call-method:mean) while the universe post correctly states
    `out == call:mean(s)`.

    Install-source digs (``_sugar_file`` / ``_sugar_source`` on the FunctionDef)
    also seed module-level ``Name = ...`` Assign constants into temporal so body
    names like ``_urlsafe_encode_translation`` reduce instead of TemporalContext
    floor-gapping before NameSugar.
    """
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.temporal import TemporalContext, bind_temporal

    module_temporal = getattr(ctx, "module_temporal", None)
    # Function construction starts from its defining module, never the caller's
    # live temporal and never the process-wide builtin seed. A module traversal
    # may provide an explicit lexical frame; install-source functions reconstruct
    # their source-owned prerequisites below.
    body_ctx = ctx.with_temporal(
        module_temporal if module_temporal is not None else TemporalContext()
    )
    body_ctx = _ctx_with_module_global_binds(site, body_ctx)
    for param_name in site.function_params():
        body_ctx = bind_temporal(
            body_ctx,
            param_name,
            SymbolicValue(make_var(param_name)),
            owner="sugar_constructors.formal_binds",
            blame=f"{getattr(site, 'filename', '')}:{getattr(site, 'line', 0)}",
        )
    return body_ctx


def _module_source_for_site(site: SourceFragment, ctx) -> tuple[str, str] | None:
    """Return the preserved defining source for a qualified install-source def.

    Module bindings belong only to FunctionDefs carrying the complete provenance
    installed-source discovery stamps. Reading another file by leaf name would
    permit two distinct modules to cross-bind; importing it would execute source.
    The preserved source text is therefore the sole construction input.
    """
    del ctx
    if site.observed != "FunctionDef":
        return None
    sugar_file = getattr(site.node, "_sugar_file", None)
    sugar_source = getattr(site.node, "_sugar_source", None)
    bridge_name = getattr(site.node, "_sugar_bridge_name", None)
    if not (
        isinstance(sugar_file, str)
        and sugar_file
        and isinstance(sugar_source, str)
        and sugar_source
        and isinstance(bridge_name, str)
        and "." in bridge_name
        and bridge_name.rsplit(".", 1)[-1] == site.function_name()
    ):
        return None
    return sugar_source, sugar_file


def _names_in_fragment(site: SourceFragment) -> list[str]:
    """Collect bare Name identifiers under ``site`` (free + bound uses)."""
    if site.observed == "Name":
        return [site.name_id()]
    if site.observed == "Call":
        names: list[str] = []
        receiver = site.call_receiver()
        if receiver is not None:
            names.extend(_names_in_fragment(receiver))
        for arg in site.call_args():
            names.extend(_names_in_fragment(arg))
        for keyword in site.call_keywords():
            names.extend(_names_in_fragment(keyword.keyword_value()))
        return names
    if site.observed == "Attribute":
        return _names_in_fragment(site.attr_receiver())
    if site.observed == "keyword":
        return _names_in_fragment(site.keyword_value())
    names = []
    for child in site.fragments():
        names.extend(_names_in_fragment(child))
    return names


def _module_level_declarations_before(
    root: SourceFragment, fn: SourceFragment
) -> list[SourceFragment]:
    """Supported top-level declarations at the function's module coordinate."""
    declarations: list[SourceFragment] = []
    fn_name = fn.function_name()
    top_level = [
        statement
        for fragment in root.fragments()
        for statement in fragment.statements()
    ]
    for statement in top_level:
        candidates = (
            [statement]
            if statement.observed == "FunctionDef"
            else [
                nested
                for nested in statement.walk()
                if nested.observed == "FunctionDef"
            ]
        )
        if any(
            candidate.function_name() == fn_name
            and (
                (fn.line and candidate.line == fn.line)
                or (not fn.line and candidate.col == fn.col)
            )
            for candidate in candidates
        ):
            return declarations
        if (
            statement.observed == "Assign"
            and statement.assign_target_name() is not None
        ):
            declarations.append(statement)
        elif statement.observed == "AnnAssign":
            try:
                statement.annassign_target_id()
            except TypeError:
                continue
            if statement.annassign_value() is not None:
                declarations.append(statement)
        elif statement.observed in ("Import", "ImportFrom"):
            declarations.append(statement)
        elif statement.observed == "Try":
            # Optional imports and try/except/else name joins (e.g. requests/help).
            declarations.append(statement)
    # Never attach declarations when the preserved tree does not contain this
    # exact function coordinate: that is stale or mismatched provenance.
    return []


def _module_declaration_bound_names(statement: SourceFragment) -> set[str]:
    """Names a static module declaration adds to its lexical frame."""
    if statement.observed == "Assign":
        name = statement.assign_target_name()
        return set() if name is None else {name}
    if statement.observed == "AnnAssign":
        try:
            return {statement.annassign_target_id()}
        except TypeError:
            return set()
    if statement.observed == "Import":
        return {
            alias or imported.split(".", 1)[0]
            for imported, alias in statement.import_names()
        }
    if statement.observed == "ImportFrom":
        return {
            alias or imported
            for imported, alias in statement.importfrom_names()
            if imported != "*"
        }
    if statement.observed == "Try":
        return _try_module_bound_names(statement)
    return set()


def _try_module_bound_names(statement: SourceFragment) -> set[str]:
    """Names a module-level Try may join into the continuing lexical frame."""
    names: set[str] = set()
    suites: list[SourceFragment] = [statement.try_body()]
    for handler in statement.try_handlers():
        suites.append(handler.except_handler_body())
    orelse = statement.try_orelse()
    if orelse is not None:
        suites.append(orelse)
    for suite in suites:
        for child in suite.statements():
            names.update(_module_declaration_bound_names(child))
    return names


def _ctx_with_module_global_binds(site: SourceFragment, ctx):
    """Construct only needed globals from a qualified def's preserved module AST.

    Supported simple assignments and import aliases are selected backwards from
    the function's module coordinate, then constructed forwards. Unsupported
    declarations are not fabricated: their names remain absent so ordinary
    TemporalContext lookup stays loud when the body demands them.
    """
    from sugar_lift_py_tests.floor import ImportAliasValue
    from sugar_lift_py_tests.outcome import Incomplete, complete_value

    loaded = _module_source_for_site(site, ctx)
    if loaded is None:
        return ctx
    source, filename = loaded
    try:
        root = SourceFragment.from_source(source, filename)
    except SyntaxError:
        return ctx

    declarations = _module_level_declarations_before(root, site)
    if not declarations:
        return ctx

    needed: set[str] = set()
    for body_stmt in site.function_body():
        needed.update(_names_in_fragment(body_stmt))
    needed -= set(site.function_params())
    if not needed:
        return ctx

    selected: list[SourceFragment] = []
    needed_work = set(needed)
    for prior in reversed(declarations):
        owned = _module_declaration_bound_names(prior)
        wanted = owned & needed_work
        if not wanted:
            continue
        selected.append(prior)
        needed_work.difference_update(wanted)
        if prior.observed == "Assign":
            needed_work.update(_names_in_fragment(prior.assign_value()))
        elif prior.observed == "AnnAssign":
            value = prior.annassign_value()
            if value is not None:
                needed_work.update(_names_in_fragment(value))
    selected.reverse()

    folded_ctx = ctx
    for prior in selected:
        if prior.observed == "Import":
            temporal = folded_ctx.temporal
            for imported, alias in prior.import_names():
                bound = alias or imported.split(".", 1)[0]
                target = imported if alias else imported.split(".", 1)[0]
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        imported,
                        bound,
                        import_target=target,
                    ),
                )
            folded_ctx = folded_ctx.with_temporal(temporal)
            continue
        if prior.observed == "ImportFrom":
            module = prior.importfrom_module()
            if prior.importfrom_level() or not module:
                continue
            temporal = folded_ctx.temporal
            for imported, alias in prior.importfrom_names():
                if imported == "*":
                    continue
                bound = alias or imported
                target = f"{module}.{imported}"
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        target,
                        bound,
                        import_target=target,
                    ),
                )
            folded_ctx = folded_ctx.with_temporal(temporal)
            continue
        # #4203: no soft TypeError/Exception continue past construction. A missing
        # shape is Incomplete (leave name unbound) or FactoryPanic (loud). Soft
        # continues laundered construction bugs into absent globals.
        outcome = folded_ctx.build_body(prior, SugarRole.STATEMENT).reduce(folded_ctx)
        if isinstance(outcome, Incomplete):
            continue
        complete_value(outcome, owner="sugar_constructors.module_global_binds")
        folded_ctx = outcome.extend_scope(folded_ctx)
    return folded_ctx


def build_bridge_body(site: SourceFragment, ctx):
    body_frags = site.function_body()
    if len(body_frags) == 1:
        body_frag = body_frags[0]
        if body_frag.observed == "Return" and body_frag.return_value() is not None:
            # Same formal binds as build_control_flow_body_sugar — required so
            # method-on-formal returns mint MethodCallStrategy (call:mean(s)),
            # not call-method:mean FactoryGap on the force_floor / bridge path.
            return _ctx_with_formal_binds(site, ctx).build_body(
                body_frag.return_value(), SugarRole.TERM
            )
    return build_control_flow_body_sugar(site, ctx)
