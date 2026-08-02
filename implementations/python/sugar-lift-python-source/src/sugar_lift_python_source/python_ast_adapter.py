from __future__ import annotations

import ast
from typing import Any, NoReturn

Json = dict[str, Any]


def _could_not_build(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    """Boundary refusal: name what the AST adapter could not construct.

    A bare ValueError at this door says neither "malformed IR" nor "unwritten
    arm." ConstructionPanic carries owner / observed / requested / fix so the
    next agent knows which of those it is.
    """
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame="python_ast_adapter",
        observed=observed,
        requested=requested,
        fix=fix,
    )


def compile_ir_document(ir: list[Json]) -> str:
    source = _source_unit_bytes(ir)
    if source is not None:
        return source

    functions = [
        _compile_contract(contract)
        for contract in ir
        if _is_function_contract(contract)
    ]
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    text = ast.unparse(module)
    return text + ("\n" if text else "")


def compile_body_term(
    term: Json, *, fn_name: str = "f", formals: list[str] | None = None
) -> str:
    contract = {
        "kind": "function-contract",
        "fnName": fn_name,
        "formals": list(formals or []),
        "post": {"args": [None, term]},
    }
    module = ast.Module(body=[_compile_contract(contract)], type_ignores=[])
    ast.fix_missing_locations(module)
    text = ast.unparse(module)
    return text + ("\n" if text else "")


def _source_unit_bytes(ir: list[Json]) -> str | None:
    for contract in ir:
        if not _is_function_contract(contract):
            continue
        term = _contract_term(contract)
        if _name(term) != "python:source-unit":
            continue
        args = term.get("args", [])
        if args and isinstance(args[0], dict) and args[0].get("kind") == "const":
            value = args[0].get("value")
            if isinstance(value, str):
                return value
    return None


def _compile_contract(contract: Json) -> ast.FunctionDef:
    fn_name = _source_function_name(str(contract["fnName"]))
    body = _stmt_list(_contract_term(contract))
    if not body:
        body = [ast.Pass()]
    args = _arguments(contract)
    return ast.FunctionDef(
        name=fn_name,
        args=args,
        body=body,
        decorator_list=[],
        returns=None,
        type_comment=None,
    )


def _arguments(contract: Json) -> ast.arguments:
    shape = contract.get("parameterShape")
    if not shape:
        formals = [
            ast.arg(arg=str(name), annotation=None, type_comment=None)
            for name in contract.get("formals", [])
        ]
        return ast.arguments(
            posonlyargs=[],
            args=formals,
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )

    posonlyargs: list[ast.arg] = []
    args: list[ast.arg] = []
    positional_defaults: list[Json | None] = []
    vararg: ast.arg | None = None
    kwonlyargs: list[ast.arg] = []
    kw_defaults: list[ast.expr | None] = []
    kwarg: ast.arg | None = None

    for raw_entry in shape:
        if not isinstance(raw_entry, dict):
            _could_not_build(
                owner="python_ast_adapter.parameterShape",
                observed=f"parameterShape entry is not an object: {raw_entry!r}",
                requested="parameterShape entry object with name and kind",
                fix="fix the IR producer of parameterShape, or reject malformed shape before compile",
            )
        name = str(raw_entry["name"])
        kind = str(raw_entry["kind"])
        arg = ast.arg(arg=name, annotation=None, type_comment=None)
        default = raw_entry.get("default")
        if kind == "positional-only":
            posonlyargs.append(arg)
            positional_defaults.append(default if isinstance(default, dict) else None)
        elif kind == "positional-or-keyword":
            args.append(arg)
            positional_defaults.append(default if isinstance(default, dict) else None)
        elif kind == "vararg":
            vararg = arg
        elif kind == "keyword-only":
            kwonlyargs.append(arg)
            kw_defaults.append(_expr(default) if isinstance(default, dict) else None)
        elif kind == "kwarg":
            kwarg = arg
        else:
            _could_not_build(
                owner="python_ast_adapter.parameterShape",
                observed=f"unsupported parameter kind: {kind}",
                requested="positional-only | positional-or-keyword | vararg | keyword-only | kwarg",
                fix=f"write parameterShape arm for kind {kind!r} or fix the producer spelling",
            )

    defaults = _trailing_defaults(positional_defaults)
    return ast.arguments(
        posonlyargs=posonlyargs,
        args=args,
        vararg=vararg,
        kwonlyargs=kwonlyargs,
        kw_defaults=kw_defaults,
        kwarg=kwarg,
        defaults=defaults,
    )


def _trailing_defaults(defaults: list[Json | None]) -> list[ast.expr]:
    first_default = next(
        (index for index, value in enumerate(defaults) if value is not None), None
    )
    if first_default is None:
        return []
    trailing = defaults[first_default:]
    if any(value is None for value in trailing):
        _could_not_build(
            owner="python_ast_adapter.parameterShape",
            observed="positional parameter defaults are not trailing",
            requested="defaults only after the first defaulted positional",
            fix="repair parameterShape defaults order at the IR producer",
        )
    return [_expr(value) for value in trailing if value is not None]


def _stmt_list(term: Json) -> list[ast.stmt]:
    if _name(term) == "python:seq":
        args = term.get("args", [])
        return _stmt_list(args[0]) + _stmt_list(args[1])
    return [_stmt(term)]


def _stmt(term: Json) -> ast.stmt:
    name = _name(term)
    args = term.get("args", [])
    if name == "python:assign":
        return ast.Assign(targets=[_target(args[0])], value=_expr(args[1]))
    if name == "python:unpack_assign":
        return ast.Assign(
            targets=[_unpack_target(args[0], args[1])],
            value=_expr(args[2]),
        )
    if name == "python:aug_assign":
        return ast.AugAssign(
            target=_target(args[0]),
            op=_augop(_const_string(args[1])),
            value=_expr(args[2]),
        )
    if name == "python:ann_assign":
        target = _target(args[0])
        return ast.AnnAssign(
            target=target,
            annotation=_expr(args[1]),
            value=None if _is_no_value(args[2]) else _expr(args[2]),
            simple=1 if isinstance(target, ast.Name) else 0,
        )
    if name == "python:return":
        value = None if _is_none_const(args[0]) else _expr(args[0])
        return ast.Return(value=value)
    if name == "python:if":
        return ast.If(
            test=_expr(args[0]),
            body=_stmt_list(args[1]) or [ast.Pass()],
            orelse=[] if _name(args[2]) == "python:pass" else _stmt_list(args[2]),
        )
    if name == "cf_ite":
        then_branch = _unguarded(args[1])
        else_branch = _unguarded(args[2])
        return ast.If(
            test=_expr(args[0]),
            body=_stmt_list(then_branch) or [ast.Pass()],
            orelse=(
                [] if _name(else_branch) == "python:pass" else _stmt_list(else_branch)
            ),
        )
    if name == "python:try":
        return ast.Try(
            body=_stmt_list(args[0]) or [ast.Pass()],
            handlers=_except_handlers(args[1]),
            orelse=[] if _name(args[2]) == "python:pass" else _stmt_list(args[2]),
            finalbody=[] if _name(args[3]) == "python:pass" else _stmt_list(args[3]),
        )
    if name == "python:import":
        if not args:
            _could_not_build(
                owner="python_ast_adapter.import",
                observed="python:import with zero bound names",
                requested="at least one bound import name",
                fix="emit bound names on python:import or drop the empty import",
            )
        return ast.Import(
            names=[ast.alias(name=_const_string(arg), asname=None) for arg in args]
        )
    if name == "python:nested_funcdef":
        return ast.FunctionDef(
            name=_const_string(args[0]),
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[],
            ),
            body=[ast.Pass()],
            decorator_list=[],
            returns=None,
            type_comment=None,
        )
    if name == "python:nested_classdef":
        return ast.ClassDef(
            name=_const_string(args[0]),
            bases=[],
            keywords=[],
            body=[ast.Pass()],
            decorator_list=[],
        )
    if name == "python:with":
        return ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=ast.Name(id="__sugar_with_context__", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    ),
                    optional_vars=None,
                )
            ],
            body=_stmt_list(args[0]) or [ast.Pass()],
            type_comment=None,
        )
    if name == "python:while":
        return ast.While(test=_expr(args[0]), body=_stmt_list(args[1]), orelse=[])
    if name == "python:for":
        return ast.For(
            target=_target(args[0]),
            iter=_expr(args[1]),
            body=_stmt_list(args[2]),
            orelse=[],
            type_comment=None,
        )
    if name == "python:expr":
        return ast.Expr(value=_expr(args[0]))
    if name == "python:pass":
        return ast.Pass()
    if name == "python:break":
        return ast.Break()
    if name == "python:continue":
        return ast.Continue()
    if name == "python:raise":
        if len(args) != 2:
            _could_not_build(
                owner="python_ast_adapter.raise",
                observed=f"python:raise arity is not exception+cause: {term!r}",
                requested="python:raise(exception, cause)",
                fix="emit both operands (use python:no_value for absent cause only)",
            )
        if _name(args[0]) == "python:no_value":
            _could_not_build(
                owner="python_ast_adapter.raise",
                observed=f"python:raise exception operand is python:no_value: {term!r}",
                requested="a concrete exception expression as the first operand",
                fix="emit the exception term; bare raise-from-handler is a different arm",
            )
        return ast.Raise(
            exc=_expr(args[0]),
            cause=None if _is_no_value(args[1]) else _expr(args[1]),
        )
    if name == "python:assert":
        return ast.Assert(
            test=_expr(args[0]),
            msg=None if _is_none_const(args[1]) else _expr(args[1]),
        )
    if name == "python:delete":
        return ast.Delete(targets=[_target(arg) for arg in args])
    return ast.Expr(value=_expr(term))


def _expr(term: Json) -> ast.expr:
    kind = term.get("kind")
    if kind == "const":
        return ast.Constant(value=_const_value(term.get("value")))
    if kind == "var":
        return ast.Name(id=str(term.get("name", "x")), ctx=ast.Load())
    if kind != "ctor":
        _could_not_build(
            owner="python_ast_adapter.term",
            observed=f"unsupported term kind: {kind!r}",
            requested="const | var | ctor",
            fix=f"write term compile arm for kind {kind!r} or fix the IR producer",
        )

    name = _name(term)
    args = term.get("args", [])
    if name == "python:annotation_union":
        return ast.BinOp(left=_expr(args[0]), op=ast.BitOr(), right=_expr(args[1]))
    if name == "python:annotation_tuple":
        return ast.Tuple(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name == "python:annotation_list":
        return ast.List(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name in _BINOPS:
        return ast.BinOp(left=_expr(args[0]), op=_BINOPS[name](), right=_expr(args[1]))
    if name in _UNARYOPS:
        return ast.UnaryOp(op=_UNARYOPS[name](), operand=_expr(args[0]))
    if name == "python:and" or name == "python:or":
        op = ast.And() if name == "python:and" else ast.Or()
        return ast.BoolOp(op=op, values=[_expr(args[0]), _expr(args[1])])
    if name == "python:compare":
        return ast.Compare(
            left=_expr(args[1]),
            ops=[_cmpop(_const_string(args[0]))],
            comparators=[_expr(args[2])],
        )
    if name == "python:ifexp":
        return ast.IfExp(
            test=_expr(args[0]), body=_expr(args[1]), orelse=_expr(args[2])
        )
    if name == "python:call":
        positional: list[ast.expr] = []
        keywords: list[ast.keyword] = []
        for arg in args[1:]:
            if _name(arg) == "python:kwarg":
                keyword_args = arg.get("args", [])
                keywords.append(
                    ast.keyword(
                        arg=_const_string(keyword_args[0]),
                        value=_expr(keyword_args[1]),
                    )
                )
            elif _name(arg) == "python:double_starred_kwarg":
                keyword_args = arg.get("args", [])
                keywords.append(ast.keyword(arg=None, value=_expr(keyword_args[0])))
            elif _name(arg) == "python:starred_arg":
                star_args = arg.get("args", [])
                positional.append(
                    ast.Starred(value=_expr(star_args[0]), ctx=ast.Load())
                )
            else:
                positional.append(_expr(arg))
        callee = (
            _dotted_expr(_const_string(args[0]))
            if _is_string_const(args[0])
            else _expr(args[0])
        )
        return ast.Call(
            func=callee,
            args=positional,
            keywords=keywords,
        )
    if name == "python:attribute":
        return ast.Attribute(
            value=_expr(args[0]), attr=_const_string(args[1]), ctx=ast.Load()
        )
    if name == "python:type_application":
        return _expr(args[1])
    if name == "python:subscript":
        return ast.Subscript(
            value=_expr(args[0]), slice=_slice_or_expr(args[1]), ctx=ast.Load()
        )
    if name == "python:tuple":
        return ast.Tuple(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name == "python:list":
        return ast.List(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name == "python:set":
        return ast.Set(elts=[_expr(arg) for arg in args])
    if name == "python:starred":
        return ast.Starred(value=_expr(args[0]), ctx=ast.Load())
    if name == "python:listcomp":
        return ast.ListComp(
            elt=_expr(args[0]),
            generators=[_comprehension(arg) for arg in args[1:]],
        )
    if name == "python:generatorexp":
        return ast.GeneratorExp(
            elt=_expr(args[0]),
            generators=[_comprehension(arg) for arg in args[1:]],
        )
    if name == "python:setcomp":
        return ast.SetComp(
            elt=_expr(args[0]),
            generators=[_comprehension(arg) for arg in args[1:]],
        )
    if name == "python:dictcomp":
        return ast.DictComp(
            key=_expr(args[0]),
            value=_expr(args[1]),
            generators=[_comprehension(arg) for arg in args[2:]],
        )
    if name == "python:lambda":
        if not args:
            _could_not_build(
                owner="python_ast_adapter.lambda",
                observed="python:lambda with no body args",
                requested="python:lambda(...params, body)",
                fix="emit the lambda body term",
            )
        return ast.Lambda(args=_lambda_arguments(args[:-1]), body=_expr(args[-1]))
    if name == "python:dict":
        keys: list[ast.expr | None] = []
        values: list[ast.expr] = []
        for entry in args:
            if _name(entry) != "python:dict_entry":
                _could_not_build(
                    owner="python_ast_adapter.dict",
                    observed=f"dict entry is not python:dict_entry: {entry!r}",
                    requested="python:dict_entry(key, value)",
                    fix="emit dict entries as python:dict_entry ctors",
                )
            entry_args = entry.get("args", [])
            key = entry_args[0]
            keys.append(None if _is_none_const(key) else _expr(key))
            values.append(_expr(entry_args[1]))
        return ast.Dict(keys=keys, values=values)
    if name == "python:fstring":
        return ast.JoinedStr(values=[_fstring_part(part) for part in args])
    if name == "python:walrus":
        return ast.NamedExpr(target=_walrus_target(args[0]), value=_expr(args[1]))
    _could_not_build(
        owner="python_ast_adapter.expr",
        observed=f"unsupported python operation in expression position: {name}",
        requested="a written python: expr ctor arm",
        fix=f"write expression compile arm for {name!r}",
    )


def _const_value(value: Any) -> object:
    if isinstance(value, dict):
        tag = value.get("type")
        if tag == "float":
            return float(str(value["repr"]))
        if tag == "bytes":
            return bytes.fromhex(str(value["repr"]))
        if tag == "complex":
            return complex(float(str(value["re"])), float(str(value["im"])))
        if tag == "ellipsis":
            return Ellipsis
        _could_not_build(
            owner="python_ast_adapter.const",
            observed=f"unsupported tagged constant type: {tag!r}",
            requested="float | bytes | complex | ellipsis (tagged const)",
            fix=f"write tagged const arm for type {tag!r}",
        )
    return value


def _slice_or_expr(term: Json) -> ast.expr | ast.slice:
    if _name(term) == "python:slice":
        args = term.get("args", [])
        return ast.Slice(
            lower=None if _is_none_const(args[0]) else _expr(args[0]),
            upper=None if _is_none_const(args[1]) else _expr(args[1]),
            step=None if _is_none_const(args[2]) else _expr(args[2]),
        )
    if _name(term) == "python:tuple":
        return ast.Tuple(
            elts=[_slice_or_expr(arg) for arg in term.get("args", [])],
            ctx=ast.Load(),
        )
    return _expr(term)


def _target(term: Json) -> ast.expr:
    name = _name(term)
    args = term.get("args", [])
    if name == "python:tuple_target":
        targets = [_target(arg) for arg in args]
        if not targets:
            _could_not_build(
                owner="python_ast_adapter.target",
                observed="empty python:tuple_target",
                requested="at least one store target",
                fix="emit one or more tuple targets",
            )
        return ast.Tuple(elts=targets, ctx=ast.Store())
    if name == "python:list_target":
        targets = [_target(arg) for arg in args]
        if not targets:
            _could_not_build(
                owner="python_ast_adapter.target",
                observed="empty python:list_target",
                requested="at least one store target",
                fix="emit one or more list targets",
            )
        return ast.List(elts=targets, ctx=ast.Store())
    if name == "python:starred":
        return ast.Starred(value=_target(args[0]), ctx=ast.Store())
    expr = _expr(term)
    return _with_context(expr, ast.Store())


def _unpack_target(kind_term: Json, targets_term: Json) -> ast.expr:
    kind = _const_string(kind_term)
    if _name(targets_term) != "python:unpack_targets":
        _could_not_build(
            owner="python_ast_adapter.unpack",
            observed=f"expected python:unpack_targets: {targets_term!r}",
            requested="python:unpack_targets(...)",
            fix="emit unpack targets under python:unpack_targets",
        )
    targets = [_target(term) for term in targets_term.get("args", [])]
    if not targets:
        _could_not_build(
            owner="python_ast_adapter.unpack",
            observed="empty unpack target list",
            requested="at least one unpack target",
            fix="emit one or more names in unpack targets",
        )
    if kind == "tuple":
        return ast.Tuple(elts=targets, ctx=ast.Store())
    if kind == "list":
        return ast.List(elts=targets, ctx=ast.Store())
    _could_not_build(
        owner="python_ast_adapter.unpack",
        observed=f"unsupported unpack target kind: {kind!r}",
        requested="tuple | list",
        fix=f"write unpack target arm for kind {kind!r}",
    )


def _unpack_name_target(term: Json) -> ast.Name:
    expr = _expr(term)
    if not isinstance(expr, ast.Name):
        _could_not_build(
            owner="python_ast_adapter.unpack",
            observed=f"unpack target is not a name: {ast.dump(expr)}",
            requested="ast.Name store target",
            fix="emit name-only unpack targets at this door",
        )
    expr.ctx = ast.Store()
    return expr


def _comprehension(term: Json) -> ast.comprehension:
    if _name(term) != "python:comprehension":
        _could_not_build(
            owner="python_ast_adapter.comprehension",
            observed=f"expected python:comprehension: {term!r}",
            requested="python:comprehension(target, iter, *ifs)",
            fix="emit comprehension generators as python:comprehension",
        )
    args = term.get("args", [])
    if len(args) < 2:
        _could_not_build(
            owner="python_ast_adapter.comprehension",
            observed=f"python:comprehension missing target/iter: {term!r}",
            requested="python:comprehension(target, iter, *ifs)",
            fix="emit at least target and iter on the comprehension",
        )
    return ast.comprehension(
        target=_comprehension_target(args[0]),
        iter=_expr(args[1]),
        ifs=[_expr(condition) for condition in args[2:]],
        is_async=0,
    )


def _comprehension_target(term: Json) -> ast.expr:
    return _with_comprehension_target_context(_expr(term))


def _lambda_arguments(param_terms: list[Json]) -> ast.arguments:
    if not param_terms:
        return _arguments({"formals": []})
    shape: list[Json] = []
    formals: list[str] = []
    for term in param_terms:
        if _is_string_const(term):
            name = _const_string(term)
            formals.append(name)
            shape.append({"name": name, "kind": "positional-or-keyword"})
            continue
        if _name(term) != "python:lambda_param":
            _could_not_build(
                owner="python_ast_adapter.lambda",
                observed=f"expected lambda parameter term: {term!r}",
                requested="string const name or python:lambda_param",
                fix="emit lambda params as names or python:lambda_param",
            )
        args = term.get("args", [])
        if len(args) != 3:
            _could_not_build(
                owner="python_ast_adapter.lambda",
                observed=f"python:lambda_param arity is not name,kind,default: {term!r}",
                requested="python:lambda_param(name, kind, default)",
                fix="emit three operands on python:lambda_param",
            )
        name = _const_string(args[0])
        kind = _const_string(args[1])
        default = args[2]
        entry: Json = {"name": name, "kind": kind}
        if not _is_no_value(default):
            entry["default"] = default
        formals.append(name)
        shape.append(entry)
    return _arguments({"formals": formals, "parameterShape": shape})


def _with_comprehension_target_context(expr: ast.expr) -> ast.expr:
    if isinstance(expr, ast.Name):
        expr.ctx = ast.Store()
        return expr
    if isinstance(expr, ast.Tuple):
        expr.elts = [_with_comprehension_target_context(elt) for elt in expr.elts]
        expr.ctx = ast.Store()
        return expr
    if isinstance(expr, ast.List):
        expr.elts = [_with_comprehension_target_context(elt) for elt in expr.elts]
        expr.ctx = ast.Store()
        return expr
    if isinstance(expr, ast.Starred):
        expr.value = _with_comprehension_target_context(expr.value)
        expr.ctx = ast.Store()
        return expr
    _could_not_build(
        owner="python_ast_adapter.comprehension",
        observed=f"comprehension target is not assignable: {ast.dump(expr)}",
        requested="Name | Tuple | List | Starred store shape",
        fix="emit an assignable comprehension target",
    )


def _except_handlers(term: Json) -> list[ast.ExceptHandler]:
    if _name(term) != "python:except_handlers":
        _could_not_build(
            owner="python_ast_adapter.except",
            observed=f"expected python:except_handlers: {term!r}",
            requested="python:except_handlers(...)",
            fix="emit handlers under python:except_handlers",
        )
    return [_except_handler(handler) for handler in term.get("args", [])]


def _except_handler(term: Json) -> ast.ExceptHandler:
    if _name(term) != "python:except_handler":
        _could_not_build(
            owner="python_ast_adapter.except",
            observed=f"expected python:except_handler: {term!r}",
            requested="python:except_handler(type, name, body)",
            fix="emit each handler as python:except_handler",
        )
    args = term.get("args", [])
    return ast.ExceptHandler(
        type=None if _is_none_const(args[0]) else _expr(args[0]),
        name=None if _is_none_const(args[1]) else _const_string(args[1]),
        body=_stmt_list(args[2]) or [ast.Pass()],
    )


def _fstring_part(term: Json) -> ast.Constant | ast.FormattedValue:
    if _is_string_const(term):
        return ast.Constant(value=_const_string(term))
    if _name(term) != "python:fstring_value":
        _could_not_build(
            owner="python_ast_adapter.fstring",
            observed=f"expected f-string part: {term!r}",
            requested="string const or python:fstring_value",
            fix="emit f-string parts as string const or python:fstring_value",
        )
    args = term.get("args", [])
    if len(args) != 3:
        _could_not_build(
            owner="python_ast_adapter.fstring",
            observed=f"python:fstring_value arity is not value,conversion,format: {term!r}",
            requested="python:fstring_value(value, conversion, format)",
            fix="emit three operands on python:fstring_value",
        )
    return ast.FormattedValue(
        value=_expr(args[0]),
        conversion=_fstring_conversion(args[1]),
        format_spec=_fstring_format_spec(args[2]),
    )


def _fstring_conversion(term: Json) -> int:
    if _is_none_const(term):
        return -1
    conversion = _const_string(term)
    if conversion not in {"a", "r", "s"}:
        _could_not_build(
            owner="python_ast_adapter.fstring",
            observed=f"unsupported f-string conversion: {conversion!r}",
            requested="a | r | s | none",
            fix=f"write conversion arm for {conversion!r} or fix the producer",
        )
    return ord(conversion)


def _fstring_format_spec(term: Json) -> ast.JoinedStr | None:
    if _is_none_const(term):
        return None
    format_spec = _expr(term)
    if not isinstance(format_spec, ast.JoinedStr):
        _could_not_build(
            owner="python_ast_adapter.fstring",
            observed=f"f-string format spec is not JoinedStr: {ast.dump(format_spec)}",
            requested="JoinedStr format_spec",
            fix="emit format_spec as a joined string expression",
        )
    return format_spec


def _walrus_target(term: Json) -> ast.Name:
    expr = _expr(term)
    if not isinstance(expr, ast.Name):
        _could_not_build(
            owner="python_ast_adapter.walrus",
            observed=f"walrus target is not a name: {ast.dump(expr)}",
            requested="ast.Name store target",
            fix="emit a name-only walrus target",
        )
    expr.ctx = ast.Store()
    return expr


def _with_context(expr: ast.expr, ctx: ast.expr_context) -> ast.expr:
    if isinstance(expr, ast.Name):
        expr.ctx = ctx
    elif isinstance(expr, ast.Attribute):
        expr.ctx = ctx
    elif isinstance(expr, ast.Subscript):
        expr.ctx = ctx
    else:
        _could_not_build(
            owner="python_ast_adapter.target",
            observed=f"term is not assignable: {ast.dump(expr)}",
            requested="Name | Attribute | Subscript store shape",
            fix="emit an assignable store target",
        )
    return expr


def _dotted_expr(name: str) -> ast.expr:
    parts = name.split(".")
    expr: ast.expr = ast.Name(id=parts[0], ctx=ast.Load())
    for part in parts[1:]:
        expr = ast.Attribute(value=expr, attr=part, ctx=ast.Load())
    return expr


def _cmpop(op: str) -> ast.cmpop:
    mapping: dict[str, type[ast.cmpop]] = {
        "==": ast.Eq,
        "!=": ast.NotEq,
        "<": ast.Lt,
        "<=": ast.LtE,
        ">": ast.Gt,
        ">=": ast.GtE,
        "is": ast.Is,
        "is not": ast.IsNot,
        "in": ast.In,
        "not in": ast.NotIn,
    }
    if op not in mapping:
        _could_not_build(
            owner="python_ast_adapter.compare",
            observed=f"unsupported comparison operator: {op!r}",
            requested="== != < <= > >= is is not in not in",
            fix=f"write comparison arm for operator {op!r}",
        )
    return mapping[op]()


def _augop(op: str) -> ast.operator:
    operator = _BINOPS.get(op)
    if operator is None:
        _could_not_build(
            owner="python_ast_adapter.aug_assign",
            observed=f"unsupported augmented assignment operator: {op!r}",
            requested="a written python: binary op used as aug-assign",
            fix=f"write aug-assign arm for operator {op!r}",
        )
    return operator()


def _contract_term(contract: Json) -> Json:
    return contract["post"]["args"][1]


def _source_function_name(fn_name: str) -> str:
    parts = [part for part in fn_name.split(".") if part != "<locals>"]
    return parts[-1] if parts else "f"


def _is_function_contract(value: Json) -> bool:
    return value.get("kind") == "function-contract"


def _name(term: Any) -> str:
    return str(term.get("name", "")) if isinstance(term, dict) else ""


def _unguarded(term: Json) -> Json:
    if _name(term) == "cf_guarded":
        args = term.get("args", [])
        if len(args) == 2:
            return args[1]
    return term


def _const_string(term: Json) -> str:
    if term.get("kind") != "const" or not isinstance(term.get("value"), str):
        _could_not_build(
            owner="python_ast_adapter.const",
            observed=f"expected string const: {term!r}",
            requested="const term with string value",
            fix="emit a string const term",
        )
    return term["value"]


def _is_string_const(term: Any) -> bool:
    return (
        isinstance(term, dict)
        and term.get("kind") == "const"
        and isinstance(term.get("value"), str)
    )


def _is_none_const(term: Any) -> bool:
    return (
        isinstance(term, dict)
        and term.get("kind") == "const"
        and term.get("value") is None
    )


def _is_no_value(term: Any) -> bool:
    return (
        isinstance(term, dict)
        and term.get("kind") == "ctor"
        and term.get("name") == "python:no_value"
        and term.get("args") == []
    )


_BINOPS: dict[str, type[ast.operator]] = {
    "python:add": ast.Add,
    "python:sub": ast.Sub,
    "python:mul": ast.Mult,
    "python:div": ast.Div,
    "python:floordiv": ast.FloorDiv,
    "python:mod": ast.Mod,
    "python:pow": ast.Pow,
    "python:lshift": ast.LShift,
    "python:rshift": ast.RShift,
    "python:bitand": ast.BitAnd,
    "python:bitor": ast.BitOr,
    "python:bitxor": ast.BitXor,
    "python:matmul": ast.MatMult,
}

_UNARYOPS: dict[str, type[ast.unaryop]] = {
    "python:neg": ast.USub,
    "python:pos": ast.UAdd,
    "python:not": ast.Not,
    "python:bitnot": ast.Invert,
}
