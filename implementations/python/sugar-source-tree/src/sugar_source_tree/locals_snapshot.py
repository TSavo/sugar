"""Where a bare ``locals()`` call is a dict of its function's parameters.

``locals()`` in a function returns a snapshot dict of the frame's bound local
variables, in the order of the code object's local names
(``co_varnames``: positional parameters, then keyword-only parameters, then
``*args``, then ``**kwargs``, then other locals).  A module-level function
has no free variables.  So before any other local is bound, the snapshot is
exactly ``{name: value}`` over the parameters, in that order.

This module answers the static half: which parameters, in which order, and
which other names the function can bind (to check none is bound yet).  It
answers only for the builtin ``locals`` (the name bound nowhere in the module)
called with no arguments directly in a module-level function's body.  A call
inside a nested function, lambda, class body, or comprehension element is
another frame.  The first iterable of a comprehension is evaluated in the
enclosing frame, so a call there is allowed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .builtin_reference import name_bound_anywhere

_PARSED: dict = {}


@dataclass(frozen=True)
class LocalsSnapshotShapeV1:
    parameters: tuple[str, ...]
    other_locals: frozenset[str]


def locals_snapshot_shape(source: str, line: int, col: int):
    """The shape of ``locals()`` at (``line``, ``col``) in ``source``, or None."""
    if "locals" not in source:
        return None
    tree = _parse(source)
    if tree is None or name_bound_anywhere(tree, "locals"):
        return None
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for statement in function.body:
            path = _path_to_call(statement, line, col)
            if path is None:
                continue
            if not _same_frame(path):
                return None
            return LocalsSnapshotShapeV1(
                parameters=_parameters(function.args),
                other_locals=frozenset(_bound_in_frame(function))
                - frozenset(_parameters(function.args)),
            )
    return None


def _parse(source):
    if source in _PARSED:
        return _PARSED[source]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if len(_PARSED) > 16:
        _PARSED.clear()
    _PARSED[source] = tree
    return tree


def _path_to_call(root, line, col):
    """Ancestors from ``root`` down to the bare ``locals()`` call at the site."""
    stack = [(root, (root,))]
    while stack:
        node, path = stack.pop()
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "locals"
            and not node.args
            and not node.keywords
            and (node.lineno, node.col_offset) == (line, col)
        ):
            return path
        for child in ast.iter_child_nodes(node):
            stack.append((child, (*path, child)))
    return None


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _same_frame(path) -> bool:
    for index, node in enumerate(path[:-1]):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return False
        if isinstance(node, _COMPREHENSIONS):
            # Only the first generator's iterable runs in the enclosing frame.
            child = path[index + 1]
            if child is not node.generators[0]:
                return False
            inner = path[index + 2] if index + 2 < len(path) else None
            if inner is not node.generators[0].iter:
                return False
    return True


def _parameters(arguments) -> tuple[str, ...]:
    names = [a.arg for a in (*arguments.posonlyargs, *arguments.args)]
    names.extend(a.arg for a in arguments.kwonlyargs)
    if arguments.vararg is not None:
        names.append(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.append(arguments.kwarg.arg)
    return tuple(names)


def _bound_in_frame(function):
    """Every name ``function``'s own frame may bind (not nested frames)."""
    bound = set()
    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            stack.extend(node.decorator_list)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, _COMPREHENSIONS):
            # Comprehension targets are the comprehension's own; a walrus in
            # it binds here, and its first iterable runs here.
            stack.append(node.generators[0].iter)
            for sub in ast.walk(node):
                if isinstance(sub, ast.NamedExpr):
                    bound.add(sub.target.id)
            continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        stack.extend(ast.iter_child_nodes(node))
    return bound
