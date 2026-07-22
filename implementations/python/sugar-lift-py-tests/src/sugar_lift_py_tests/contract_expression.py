# SPDX-License-Identifier: MIT OR Apache-2.0
"""Parse string contract expressions into IR formulas via ast.

Not a second SourceFragment. Source currency is one: sugar_source_tree
SourceFragment, sealed only through the one SourceOracle. Contract
strings are small formula text; they parse with the stdlib ast module.
"""

from __future__ import annotations

import ast
import textwrap

from .ir import (
    Formula,
    and_,
    bool_const,
    comparison_with_none_guard,
    ctor,
    eq,
    make_var,
    not_,
    num,
    or_,
    str_const,
)


def parse_contract_expression(expr: str, available_names: list[str]) -> Formula:
    """Parse a string contract expression into a canonical IR formula."""
    source = textwrap.dedent(expr).strip()
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"empty or invalid contract expression: {expr!r}") from exc
    return _translate_expr(tree.body, available_names)


_COMPARE_OPS = {
    ast.Eq: "=",
    ast.NotEq: "≠",
    ast.Lt: "<",
    ast.LtE: "≤",
    ast.Gt: ">",
    ast.GtE: "≥",
    ast.Is: "=",
    ast.IsNot: "≠",
}


def _translate_expr(node: ast.AST, available_names: list[str]) -> Formula:
    if isinstance(node, ast.BoolOp):
        operands = [_translate_expr(value, available_names) for value in node.values]
        if isinstance(node.op, ast.And):
            return and_(operands)
        if isinstance(node.op, ast.Or):
            return or_(operands)
        raise ValueError(f"unsupported bool op: {type(node.op).__name__}")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not_(_translate_expr(node.operand, available_names))

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("chained comparisons are not supported")
        symbol = _COMPARE_OPS.get(type(node.ops[0]))
        if symbol is None:
            raise ValueError(f"unsupported comparison: {type(node.ops[0]).__name__}")
        left = _translate_term(node.left, available_names)
        right = _translate_term(node.comparators[0], available_names)
        return comparison_with_none_guard(symbol, left, right)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _translate_term(node.left, available_names)
        right = _translate_term(node.right, available_names)
        term = ctor("+", [left, right])
        return eq(term, term)

    term = _translate_term(node, available_names)
    return eq(term, bool_const(True))


def _translate_term(node: ast.AST, available_names: list[str]):
    if isinstance(node, ast.Name):
        name = node.id
        if name == "None":
            return ctor("None", [])
        if name == "True":
            return bool_const(True)
        if name == "False":
            return bool_const(False)
        return make_var(name)

    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return num(value)
        if isinstance(value, str):
            return str_const(value)
        if value is None:
            return ctor("None", [])
        raise ValueError(f"unsupported constant: {type(value).__name__}")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if isinstance(node.operand, ast.Constant) and isinstance(
            node.operand.value, int
        ):
            return num(-node.operand.value)
        raise ValueError("unary minus only supported on integer literals")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple-name calls are supported")
        arguments = [
            _translate_term(argument, available_names) for argument in node.args
        ]
        return ctor(node.func.id, arguments)

    if isinstance(node, ast.BinOp):
        symbols = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
        }
        symbol = symbols.get(type(node.op))
        if symbol is None:
            raise ValueError(f"unsupported binary op: {type(node.op).__name__}")
        left = _translate_term(node.left, available_names)
        right = _translate_term(node.right, available_names)
        return ctor(symbol, [left, right])

    raise ValueError(f"unsupported expression: {type(node).__name__}")
