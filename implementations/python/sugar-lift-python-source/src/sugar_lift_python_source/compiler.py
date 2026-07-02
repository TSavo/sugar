from __future__ import annotations

import ast
from typing import Any

Json = dict[str, Any]


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
            raise ValueError(f"parameterShape entry is not an object: {raw_entry!r}")
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
            raise ValueError(f"unsupported parameter kind: {kind}")

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
        raise ValueError("positional parameter defaults must be trailing")
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
            raise ValueError("python:import needs at least one bound name")
        return ast.Import(
            names=[
                ast.alias(name=_const_string(arg), asname=None)
                for arg in args
            ]
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
        return ast.Raise(
            exc=None if _is_none_const(args[0]) else _expr(args[0]), cause=None
        )
    if name == "python:assert":
        return ast.Assert(
            test=_expr(args[0]),
            msg=None if _is_none_const(args[1]) else _expr(args[1]),
        )
    return ast.Expr(value=_expr(term))


def _expr(term: Json) -> ast.expr:
    kind = term.get("kind")
    if kind == "const":
        return ast.Constant(value=_const_value(term.get("value")))
    if kind == "var":
        return ast.Name(id=str(term.get("name", "x")), ctx=ast.Load())
    if kind != "ctor":
        raise ValueError(f"unsupported term kind: {kind}")

    name = _name(term)
    args = term.get("args", [])
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
        return ast.IfExp(test=_expr(args[0]), body=_expr(args[1]), orelse=_expr(args[2]))
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
    if name == "python:subscript":
        return ast.Subscript(
            value=_expr(args[0]), slice=_slice_or_expr(args[1]), ctx=ast.Load()
        )
    if name == "python:tuple":
        return ast.Tuple(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name == "python:list":
        return ast.List(elts=[_expr(arg) for arg in args], ctx=ast.Load())
    if name == "python:listcomp":
        return ast.ListComp(
            elt=_expr(args[0]),
            generators=[_comprehension(arg) for arg in args[1:]],
        )
    if name == "python:lambda":
        if not args:
            raise ValueError("python:lambda needs a body")
        return ast.Lambda(args=_lambda_arguments(args[:-1]), body=_expr(args[-1]))
    if name == "python:dict":
        keys: list[ast.expr | None] = []
        values: list[ast.expr] = []
        for entry in args:
            if _name(entry) != "python:dict_entry":
                raise ValueError(f"expected python:dict_entry: {entry!r}")
            entry_args = entry.get("args", [])
            key = entry_args[0]
            keys.append(None if _is_none_const(key) else _expr(key))
            values.append(_expr(entry_args[1]))
        return ast.Dict(keys=keys, values=values)
    if name == "python:fstring":
        return ast.JoinedStr(values=[_fstring_part(part) for part in args])
    if name == "python:walrus":
        return ast.NamedExpr(target=_walrus_target(args[0]), value=_expr(args[1]))
    raise ValueError(f"unsupported python operation in expression position: {name}")


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
        raise ValueError(f"unsupported tagged constant type: {tag}")
    return value


def _slice_or_expr(term: Json) -> ast.expr | ast.slice:
    if _name(term) == "python:slice":
        args = term.get("args", [])
        return ast.Slice(
            lower=None if _is_none_const(args[0]) else _expr(args[0]),
            upper=None if _is_none_const(args[1]) else _expr(args[1]),
            step=None if _is_none_const(args[2]) else _expr(args[2]),
        )
    return _expr(term)


def _target(term: Json) -> ast.expr:
    name = _name(term)
    args = term.get("args", [])
    if name == "python:tuple_target":
        targets = [_target(arg) for arg in args]
        if not targets:
            raise ValueError("tuple target must contain at least one target")
        return ast.Tuple(elts=targets, ctx=ast.Store())
    if name == "python:list_target":
        targets = [_target(arg) for arg in args]
        if not targets:
            raise ValueError("list target must contain at least one target")
        return ast.List(elts=targets, ctx=ast.Store())
    expr = _expr(term)
    return _with_context(expr, ast.Store())


def _unpack_target(kind_term: Json, targets_term: Json) -> ast.expr:
    kind = _const_string(kind_term)
    if _name(targets_term) != "python:unpack_targets":
        raise ValueError(f"expected python:unpack_targets: {targets_term!r}")
    targets = [_target(term) for term in targets_term.get("args", [])]
    if not targets:
        raise ValueError("unpack target must contain at least one name")
    if kind == "tuple":
        return ast.Tuple(elts=targets, ctx=ast.Store())
    if kind == "list":
        return ast.List(elts=targets, ctx=ast.Store())
    raise ValueError(f"unsupported unpack target kind: {kind}")


def _unpack_name_target(term: Json) -> ast.Name:
    expr = _expr(term)
    if not isinstance(expr, ast.Name):
        raise ValueError(f"unpack target is not a name: {ast.dump(expr)}")
    expr.ctx = ast.Store()
    return expr


def _comprehension(term: Json) -> ast.comprehension:
    if _name(term) != "python:comprehension":
        raise ValueError(f"expected python:comprehension: {term!r}")
    args = term.get("args", [])
    if len(args) < 2:
        raise ValueError(f"python:comprehension needs target and iter: {term!r}")
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
            raise ValueError(f"expected lambda parameter term: {term!r}")
        args = term.get("args", [])
        if len(args) != 3:
            raise ValueError(f"python:lambda_param needs name, kind, default: {term!r}")
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
    raise ValueError(f"comprehension target is not assignable: {ast.dump(expr)}")


def _except_handlers(term: Json) -> list[ast.ExceptHandler]:
    if _name(term) != "python:except_handlers":
        raise ValueError(f"expected python:except_handlers: {term!r}")
    return [_except_handler(handler) for handler in term.get("args", [])]


def _except_handler(term: Json) -> ast.ExceptHandler:
    if _name(term) != "python:except_handler":
        raise ValueError(f"expected python:except_handler: {term!r}")
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
        raise ValueError(f"expected f-string part: {term!r}")
    args = term.get("args", [])
    if len(args) != 3:
        raise ValueError(
            f"expected python:fstring_value(value, conversion, format): {term!r}"
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
        raise ValueError(f"unsupported f-string conversion: {conversion}")
    return ord(conversion)


def _fstring_format_spec(term: Json) -> ast.JoinedStr | None:
    if _is_none_const(term):
        return None
    format_spec = _expr(term)
    if not isinstance(format_spec, ast.JoinedStr):
        raise ValueError(
            f"f-string format spec is not JoinedStr: {ast.dump(format_spec)}"
        )
    return format_spec


def _walrus_target(term: Json) -> ast.Name:
    expr = _expr(term)
    if not isinstance(expr, ast.Name):
        raise ValueError(f"walrus target is not a name: {ast.dump(expr)}")
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
        raise ValueError(f"term is not assignable: {ast.dump(expr)}")
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
        raise ValueError(f"unsupported comparison operator: {op}")
    return mapping[op]()


def _augop(op: str) -> ast.operator:
    operator = _BINOPS.get(op)
    if operator is None:
        raise ValueError(f"unsupported augmented assignment operator: {op}")
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
        raise ValueError(f"expected string const: {term!r}")
    return term["value"]


def _is_string_const(term: Any) -> bool:
    return isinstance(term, dict) and term.get("kind") == "const" and isinstance(
        term.get("value"), str
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
}

_UNARYOPS: dict[str, type[ast.unaryop]] = {
    "python:neg": ast.USub,
    "python:pos": ast.UAdd,
    "python:not": ast.Not,
    "python:bitnot": ast.Invert,
}
