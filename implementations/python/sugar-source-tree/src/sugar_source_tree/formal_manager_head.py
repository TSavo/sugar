"""Which ``with`` heads select their manager from a parameter.

A head qualifies when evaluating it can only read the parameter and then run
attribute reads and calls with constant arguments on it: ``monkeypatch.context()``,
``self.buffer``, ``p``.  The parameter belongs to the innermost function around
the ``with`` (no class body, lambda or nested function in between) and is
never rebound in that function, so at the ``with`` it still holds the value the
caller passed.  Anything else returns ``None``.
"""

from __future__ import annotations

import ast

from .builtin_reference import name_bound_anywhere, parsed_module


def formal_manager_head(source: str, start_line: int, start_col: int):
    """The head's source text when the With item at the site is formal-rooted."""
    tree = parsed_module(source)
    if tree is None:
        return None
    found = _with_item_expr(tree, start_line, start_col)
    if found is None:
        return None
    function, expr = found
    root = _chain_root(expr)
    if root is None:
        return None
    arguments = function.args
    parameters = {
        arg.arg
        for arg in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *(a for a in (arguments.vararg, arguments.kwarg) if a is not None),
        )
    }
    if root not in parameters:
        return None
    if any(name_bound_anywhere(statement, root) for statement in function.body):
        return None
    return ast.unparse(expr)


def _chain_root(expr):
    node = expr
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        if isinstance(node, ast.Call):
            if not all(isinstance(arg, ast.Constant) for arg in node.args):
                return None
            if not all(
                keyword.arg is not None and isinstance(keyword.value, ast.Constant)
                for keyword in node.keywords
            ):
                return None
            node = node.func
            continue
        return None


def _with_item_expr(tree, line, col):
    """``(innermost function, context_expr)`` for the With item at the site."""
    stack = [(tree, None)]
    while stack:
        node, function = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node
        elif isinstance(node, (ast.Lambda, ast.ClassDef)):
            function = None
        if isinstance(node, ast.With) and function is not None:
            for item in node.items:
                expr = item.context_expr
                if (expr.lineno, expr.col_offset) == (line, col):
                    return function, expr
        for child in ast.iter_child_nodes(node):
            stack.append((child, function))
    return None
