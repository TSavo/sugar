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
    root = _chain_root(expr, operands_admitted=True)
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
        root = _parameter_alias(function, root, parameters, expr)
        if root is None:
            return None
    if any(name_bound_anywhere(statement, root) for statement in function.body):
        return None
    return ast.unparse(expr)


def _parameter_alias(function, name, parameters, expr):
    """The parameter a local names when it is only ever ``name = <parameter>``.

    ``parser = all_parsers`` as one top-level statement of the function, the
    local's only binding anywhere in it, and lexically before the ``with``:
    top-level statements run in order, so at the ``with`` the local holds the
    very object the caller passed for that parameter.
    """
    binders = [
        statement
        for statement in function.body
        if name_bound_anywhere(statement, name)
    ]
    if len(binders) != 1:
        return None
    statement = binders[0]
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == name
        and isinstance(statement.value, ast.Name)
        and statement.value.id in parameters
    ):
        return None
    if statement.end_lineno >= expr.lineno:
        return None
    return statement.value.id


def _chain_root(expr, *, operands_admitted=False):
    """The chain's root name.

    Calls inside the chain take constant arguments only.  The OUTERMOST call
    -- the one that produces the manager -- may take any operands: they are
    evaluated as ordinary expressions between selecting the callee and
    calling it (``FormalSelectedManagerHeadSugar``), so their effects are kept.
    """
    node = expr
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
            operands_admitted = False
            continue
        if isinstance(node, ast.Call):
            if not operands_admitted:
                if not all(isinstance(arg, ast.Constant) for arg in node.args):
                    return None
                if not all(
                    keyword.arg is not None
                    and isinstance(keyword.value, ast.Constant)
                    for keyword in node.keywords
                ):
                    return None
            operands_admitted = False
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


def runtime_selected_manager_head(source: str, start_line: int, start_col: int):
    """The head's source text when its manager is selected by name at run time.

    The head is a chain (attribute reads, constant-argument calls, operands on
    the outermost call) rooted at a local of the innermost function around the
    ``with`` whose only binding in that function is one top-level statement
    ``local = getattr(<object>, <name>)``, lexically before the ``with``, with
    a ``<name>`` that is not a constant and the builtin ``getattr`` (the
    module binds no ``getattr``).  At the ``with`` the local holds whatever
    attribute that run-time string names (``klass = getattr(module, klass)``
    then ``with klass(path) as f:``): no source decides the manager, so there
    is no callee to read.  Anything else returns ``None``.
    """
    tree = parsed_module(source)
    if tree is None:
        return None
    found = _with_item_expr(tree, start_line, start_col)
    if found is None:
        return None
    function, expr = found
    root = _chain_root(expr, operands_admitted=True)
    if root is None or name_bound_anywhere(tree, "getattr"):
        return None
    binders = [
        statement
        for statement in function.body
        if name_bound_anywhere(statement, root)
    ]
    if len(binders) != 1:
        return None
    statement = binders[0]
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == root
        and _run_time_getattr(statement.value)
    ):
        return None
    if statement.end_lineno >= expr.lineno:
        return None
    return ast.unparse(expr)


def _run_time_getattr(value) -> bool:
    """``getattr(<object>, <non-constant name>)`` with no default."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "getattr"
        and len(value.args) == 2
        and not value.keywords
        and not any(isinstance(arg, ast.Starred) for arg in value.args)
        and not isinstance(value.args[1], ast.Constant)
    )
