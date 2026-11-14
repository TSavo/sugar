"""Whether a name in a module can only refer to Python's own builtin.

A name that no scope of the module binds is looked up in the module's globals
and then in ``builtins``. So when the module binds it nowhere (no assignment,
import, star import, definition, parameter, ``global``/``nonlocal``
declaration, exception, ``match`` capture or type parameter), every load of it
reads the builtin. This check is static and covers the whole module, so a
binding in any scope rules the name out.
"""

from __future__ import annotations

import ast
import builtins

_PARSED: dict = {}


def parsed_module(source: str):
    """``ast.parse(source)``, cached per source text; None when it does not parse."""
    tree = _PARSED.get(source)
    if tree is None and source not in _PARSED:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            tree = None
        _PARSED[source] = tree
    return tree


def name_bound_anywhere(tree, name: str) -> bool:
    """Whether any scope of ``tree`` binds ``name``, or a star import might."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name and not isinstance(
            node.ctx, ast.Load
        ):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        if isinstance(node, ast.arg) and node.arg == name:
            return True
        if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*" or (alias.asname or alias.name.split(".")[0]) == name:
                    return True
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            return True
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name:
            return True
        if isinstance(node, ast.MatchMapping) and node.rest == name:
            return True
        if getattr(node, "type_params", None):
            if any(getattr(param, "name", None) == name for param in node.type_params):
                return True
    return False


def module_reads_builtin(source: str, name: str) -> bool:
    """Whether every load of ``name`` in ``source`` reads ``builtins.<name>``."""
    if not hasattr(builtins, name):
        return False
    tree = parsed_module(source)
    return tree is not None and not name_bound_anywhere(tree, name)


# Names the interpreter binds without a source binding: the module attributes
# the import system sets, the class-body names, and the implicit ``__class__``
# cell of a method.
_IMPLICIT_NAMES = frozenset(
    (
        "__name__",
        "__file__",
        "__doc__",
        "__spec__",
        "__loader__",
        "__package__",
        "__path__",
        "__cached__",
        "__builtins__",
        "__annotations__",
        "__dict__",
        "__module__",
        "__qualname__",
        "__class__",
    )
)

# A read of one of these can write a global (or a builtin) the source never
# spells as a binding, so no read in that module is called unbound.
_DYNAMIC_GLOBAL_WRITERS = frozenset(
    ("globals", "vars", "locals", "exec", "eval", "builtins", "__builtins__")
)


def module_name_unbound(source: str, name: str) -> bool:
    """Whether every load of ``name`` in ``source`` raises ``NameError``.

    True only when nothing binds the name: no scope of the module (the one
    ``name_bound_anywhere`` reading, star imports included), not a builtin,
    not a name the interpreter binds itself, and no read of a dynamic global
    writer in the module. Any doubt answers False.
    """
    if hasattr(builtins, name) or name in _IMPLICIT_NAMES:
        return False
    tree = parsed_module(source)
    if tree is None or name_bound_anywhere(tree, name):
        return False
    return not any(
        isinstance(node, ast.Name) and node.id in _DYNAMIC_GLOBAL_WRITERS
        for node in ast.walk(tree)
    )
