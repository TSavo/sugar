from __future__ import annotations

import ast
from typing import Any

Json = Any


def function_param_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [arg.arg for arg in _ordered_signature_args(node.args)]


def function_body_template(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Json:
    return block_to_ast_template(node.body, function_param_names(node))


def block_to_ast_template(statements: list[ast.stmt], params: list[str]) -> Json:
    return {
        "kind": "block",
        "stmts": [stmt_to_template(stmt, params) for stmt in statements],
    }


def stmt_to_template(stmt: ast.stmt, params: list[str]) -> Json:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return {"kind": "other", "variant": "multi_assign"}
        return {
            "kind": "let",
            "pat": pat_to_template(stmt.targets[0], params),
            "init": expr_to_template(stmt.value, params),
        }
    if isinstance(stmt, ast.AnnAssign):
        return {
            "kind": "let",
            "pat": pat_to_template(stmt.target, params),
            "init": (
                expr_to_template(stmt.value, params) if stmt.value is not None else None
            ),
        }
    if isinstance(stmt, ast.Expr):
        # Python expression statements do not carry Rust's semicolon signal.
        return {
            "kind": "expr_stmt",
            "expr": expr_to_template(stmt.value, params),
            "trailing_semi": False,
        }
    if isinstance(stmt, ast.Return):
        return {
            "kind": "expr_stmt",
            "expr": {
                "kind": "return",
                "expr": (
                    expr_to_template(stmt.value, params)
                    if stmt.value is not None
                    else None
                ),
            },
            "trailing_semi": False,
        }
    return {"kind": "other", "variant": type(stmt).__name__}


def expr_to_template(expr: ast.expr, params: list[str]) -> Json:
    if isinstance(expr, ast.Call):
        args = [expr_to_template(arg, params) for arg in expr.args]
        args.extend(kwarg_to_template(keyword, params) for keyword in expr.keywords)
        if isinstance(expr.func, ast.Attribute):
            return {
                "kind": "method_call",
                "receiver": expr_to_template(expr.func.value, params),
                "method": expr.func.attr,
                "args": args,
            }
        return {
            "kind": "call",
            "func": expr_to_template(expr.func, params),
            "args": args,
        }
    if isinstance(expr, ast.Name):
        if expr.id in params:
            return {"kind": "param_ref", "index": params.index(expr.id) + 1}
        return {"kind": "ident", "name": expr.id}
    if isinstance(expr, ast.Attribute):
        field = _field_template_if_param_root(expr, params)
        if field is not None:
            return field
        segments = _attribute_segments(expr)
        if segments is not None:
            return {"kind": "path", "segments": segments}
        return {
            "kind": "field",
            "base": expr_to_template(expr.value, params),
            "member": expr.attr,
        }
    if isinstance(expr, ast.Constant):
        return lit_to_template(expr.value)
    if isinstance(expr, ast.Tuple):
        return {
            "kind": "tuple",
            "elems": [expr_to_template(elt, params) for elt in expr.elts],
        }
    if isinstance(expr, ast.List):
        return {
            "kind": "array",
            "elems": [expr_to_template(elt, params) for elt in expr.elts],
        }
    if isinstance(expr, ast.BinOp):
        return {
            "kind": "binary",
            "op": type(expr.op).__name__,
            "left": expr_to_template(expr.left, params),
            "right": expr_to_template(expr.right, params),
        }
    if isinstance(expr, ast.UnaryOp):
        return {
            "kind": "unary",
            "op": type(expr.op).__name__,
            "expr": expr_to_template(expr.operand, params),
        }
    if isinstance(expr, ast.NamedExpr):
        return {
            "kind": "let",
            "pat": pat_to_template(expr.target, params),
            "init": expr_to_template(expr.value, params),
        }
    if isinstance(expr, ast.Await):
        return {"kind": "await", "expr": expr_to_template(expr.value, params)}
    if isinstance(expr, ast.Starred):
        return {"kind": "starred", "expr": expr_to_template(expr.value, params)}
    return {"kind": "other", "variant": type(expr).__name__}


def kwarg_to_template(keyword: ast.keyword, params: list[str]) -> Json:
    # Python kwargs are source-level semantics, so keep the name instead of
    # flattening away the distinction between f(x=a) and f(y=a).
    return {
        "kind": "kwarg",
        "name": keyword.arg,
        "value": expr_to_template(keyword.value, params),
    }


def pat_to_template(node: ast.AST, params: list[str]) -> Json:
    if isinstance(node, ast.Name):
        if node.id in params:
            return {"kind": "param_ref", "index": params.index(node.id) + 1}
        return {"kind": "binding", "name": node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            "kind": "pat_tuple",
            "elems": [pat_to_template(elt, params) for elt in node.elts],
        }
    if isinstance(node, ast.Starred):
        return {"kind": "pat_starred", "pat": pat_to_template(node.value, params)}
    return {"kind": "pat_other"}


def lit_to_template(value: object) -> Json:
    if isinstance(value, bool):
        return {"kind": "lit", "ty": "bool", "value": value}
    if isinstance(value, str):
        return {"kind": "lit", "ty": "str", "value": value}
    if isinstance(value, int):
        return {"kind": "lit", "ty": "int", "value": value}
    if isinstance(value, float):
        return {"kind": "lit", "ty": "float", "value": value}
    if value is None:
        return {"kind": "lit", "ty": "none", "value": None}
    return {"kind": "lit", "ty": type(value).__name__, "value": repr(value)}


def _ordered_signature_args(args: ast.arguments) -> list[ast.arg]:
    ordered_args: list[ast.arg] = []
    ordered_args.extend(args.posonlyargs)
    ordered_args.extend(args.args)
    if args.vararg is not None:
        ordered_args.append(args.vararg)
    ordered_args.extend(args.kwonlyargs)
    if args.kwarg is not None:
        ordered_args.append(args.kwarg)
    return ordered_args


def _attribute_segments(expr: ast.Attribute) -> list[str] | None:
    segments: list[str] = []
    current: ast.AST = expr
    while isinstance(current, ast.Attribute):
        segments.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        segments.append(current.id)
        return list(reversed(segments))
    return None


def _field_template_if_param_root(
    expr: ast.Attribute, params: list[str]
) -> Json | None:
    parts: list[str] = []
    current: ast.AST = expr
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id not in params:
        return None
    result: Json = {"kind": "param_ref", "index": params.index(current.id) + 1}
    for member in reversed(parts):
        result = {"kind": "field", "base": result, "member": member}
    return result
