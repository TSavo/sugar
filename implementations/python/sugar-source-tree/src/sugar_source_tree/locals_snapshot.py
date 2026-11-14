"""Where a bare ``locals()`` call is a dict of its function's parameters.

``locals()`` in a function returns a snapshot dict of the frame's bound local
variables, in the order of the code object's local names
(``co_varnames``: positional parameters, then keyword-only parameters, then
``*args``, then ``**kwargs``, then other locals).  A module-level function
has no free variables.  So before any other local is bound, the snapshot is
exactly ``{name: value}`` over the parameters, in that order.

This module answers the static half: which parameters, in which order, and
which other names the function can bind (to check none is bound yet).  It
answers only for the builtin ``locals`` (the read the unit resolves to
``builtins.locals``) called with no arguments directly in a module-level
function's body.  A call inside a nested function, lambda, class body, or
comprehension element is another frame.  The first iterable of a
comprehension is evaluated in the enclosing frame, so a call there is allowed.

Everything is read off the unit's typed tree; the source is never parsed here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalsSnapshotShapeV1:
    parameters: tuple[str, ...]
    other_locals: frozenset[str]


def locals_snapshot_shape(unit, line: int, col: int):
    """The shape of ``locals()`` at (``line``, ``col``) in ``unit``, or None."""
    from .nodes import AsyncFunctionDef, FunctionDef

    module = unit.typed_module
    if module is None:
        return None
    for function in module.body:
        if not isinstance(function, (FunctionDef, AsyncFunctionDef)):
            continue
        for statement in function.body:
            path = _path_to_call(unit, statement, line, col)
            if path is None:
                continue
            if not _same_frame(path):
                return None
            parameters = _parameters(function)
            return LocalsSnapshotShapeV1(
                parameters=parameters,
                other_locals=frozenset(_bound_in_frame(function))
                - frozenset(parameters),
            )
    return None


def _path_to_call(unit, root, line, col):
    """Ancestors from ``root`` down to the bare ``locals()`` call at the site:
    the call whose callee the unit binds to ``builtins.locals``
    (``SourceUnit.language_callee_of``), never the spelling."""
    from .nodes import Call, LanguageCallee

    stack = [(root, (root,))]
    while stack:
        node, path = stack.pop()
        if isinstance(node, Call) and not node.args and not node.keywords:
            span = node.line_col_span()
            if (span.start_line, span.start_col) == (line, col) and (
                unit.language_callee_of(node.func) is LanguageCallee.BUILTIN_LOCALS
            ):
                return path
        for _name, _index, child in node.children():
            stack.append((child, (*path, child)))
    return None


def _edge(parent, child):
    """``(field, index)`` of the edge from ``parent`` to ``child``."""
    for name, index, candidate in parent.children():
        if candidate is child:
            return name, index
    return None


def _same_frame(path) -> bool:
    from .nodes import (
        AsyncFunctionDef,
        ClassDef,
        DictComp,
        FunctionDef,
        GeneratorExp,
        Lambda,
        ListComp,
        SetComp,
    )

    for index, node in enumerate(path[:-1]):
        if isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda, ClassDef)):
            return False
        if isinstance(node, (ListComp, SetComp, DictComp, GeneratorExp)):
            # Only the first generator's iterable runs in the enclosing frame.
            generator = path[index + 1]
            if _edge(node, generator) != ("generators", 0):
                return False
            inner = path[index + 2] if index + 2 < len(path) else None
            if inner is None or _edge(generator, inner) != ("iter", None):
                return False
    return True


def _parameters(function) -> tuple[str, ...]:
    arguments = function.args
    names = [p.name for p in (*arguments.posonlyargs, *arguments.args)]
    names.extend(p.name for p in arguments.kwonlyargs)
    if arguments.vararg is not None:
        names.append(arguments.vararg.name)
    if arguments.kwarg is not None:
        names.append(arguments.kwarg.name)
    return tuple(names)


def _bound_in_frame(function):
    """Every name ``function``'s own frame may bind (not nested frames)."""
    from .nodes import (
        AsyncFunctionDef,
        ClassDef,
        DictComp,
        FunctionDef,
        GeneratorExp,
        Global,
        Lambda,
        ListComp,
        NamedExpr,
        Nonlocal,
        SetComp,
    )

    bound = set()
    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (FunctionDef, AsyncFunctionDef, ClassDef)):
            bound.add(node.name)
            stack.extend(node.decorators)
            continue
        if isinstance(node, Lambda):
            continue
        if isinstance(node, (ListComp, SetComp, DictComp, GeneratorExp)):
            # Comprehension targets are the comprehension's own; a walrus in
            # it binds here, and its first iterable runs here.
            stack.append(node.generators[0].iter)
            for sub in node.walk():
                if isinstance(sub, NamedExpr):
                    bound.update(sub.names_bound_here())
            continue
        if not isinstance(node, (Global, Nonlocal)):
            # A declaration routes a name elsewhere; it binds no local.
            bound.update(node.names_bound_here())
        stack.extend(child for _name, _index, child in node.children())
    return bound
