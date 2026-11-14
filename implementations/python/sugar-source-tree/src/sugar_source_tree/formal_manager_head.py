"""Which ``with`` heads select their manager from a parameter.

A head qualifies when evaluating it can only read the parameter and then run
attribute reads and calls with constant arguments on it: ``monkeypatch.context()``,
``self.buffer``, ``p``.  The parameter belongs to the innermost function around
the ``with`` (no class body, lambda or nested function in between) and is
never rebound in that function, so at the ``with`` it still holds the value the
caller passed.  Anything else returns ``None``.

Every reader here takes the typed ``SourceUnit`` the ``with`` belongs to and
walks its node tree; the source is never parsed here.  A head's text is its
own source segment.
"""

from __future__ import annotations


def _binds(node, name: str) -> bool:
    """Whether ``node`` or anything under it binds ``name`` (or may: ``*``)."""
    names = node.names_bound_within()
    return name in names or "*" in names


def _parameters(function) -> set[str]:
    return {param.name for param in function.params}


def formal_manager_head(unit, start_line: int, start_col: int):
    """The head's source text when the With item at the site is formal-rooted."""
    found = _with_item_expr(unit, start_line, start_col)
    if found is None:
        return None
    function, expr = found
    root = _chain_root(expr, operands_admitted=True)
    if root is None:
        return None
    parameters = _parameters(function)
    if root not in parameters:
        root = _parameter_alias(function, root, parameters, expr)
        if root is None:
            return None
    if any(_binds(statement, root) for statement in function.body):
        return None
    return expr.segment()


def _parameter_alias(function, name, parameters, expr):
    """The parameter a local names when it is only ever ``name = <parameter>``.

    ``parser = all_parsers`` as one top-level statement of the function, the
    local's only binding anywhere in it, and lexically before the ``with``:
    top-level statements run in order, so at the ``with`` the local holds the
    very object the caller passed for that parameter.
    """
    from .nodes import Assign, Name

    binders = [statement for statement in function.body if _binds(statement, name)]
    if len(binders) != 1:
        return None
    statement = binders[0]
    if not (
        isinstance(statement, Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], Name)
        and statement.targets[0].id == name
        and isinstance(statement.value, Name)
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
    from .nodes import Attribute, Call, Constant, Name

    node = expr
    while True:
        if isinstance(node, Name):
            return node.id
        if isinstance(node, Attribute):
            node = node.value
            operands_admitted = False
            continue
        if isinstance(node, Call):
            if not operands_admitted:
                if not all(isinstance(arg, Constant) for arg in node.args):
                    return None
                if not all(
                    keyword.arg is not None and isinstance(keyword.value, Constant)
                    for keyword in node.keywords
                ):
                    return None
            operands_admitted = False
            node = node.func
            continue
        return None


def _with_item_expr(unit, line, col):
    """``(innermost function, context_expr)`` for the With item at the site."""
    from .nodes import AsyncFunctionDef, ClassDef, FunctionDef, Lambda, With

    module = unit._require_typed_module(
        "formal_manager_head._with_item_expr", blame=f"{unit.filename}:{line}:{col}"
    )
    stack = [(module, None)]
    while stack:
        node, function = stack.pop()
        if isinstance(node, (FunctionDef, AsyncFunctionDef)):
            function = node
        elif isinstance(node, (Lambda, ClassDef)):
            function = None
        if isinstance(node, With) and function is not None:
            for item in node.items:
                expr = item.context_expr
                span = expr.line_col_span()
                if (span.start_line, span.start_col) == (line, col):
                    return function, expr
        for _name, _index, child in node.children():
            stack.append((child, function))
    return None


def runtime_selected_manager_head(unit, start_line: int, start_col: int):
    """The head's source text when its manager is selected by name at run time.

    ``unit`` is the typed ``SourceUnit`` the ``with`` belongs to; its node tree
    is the tree read here, and it answers how the callee of the binding
    statement is bound.

    The head is a chain (attribute reads, constant-argument calls, operands on
    the outermost call) rooted at a local of the innermost function around the
    ``with`` whose only binding in that function is one top-level statement
    ``local = getattr(<object>, <name>)``, lexically before the ``with``, with
    a ``<name>`` that is not a constant and a callee bound to the builtin
    ``getattr`` (``LanguageCallee.BUILTIN_GETATTR``, by its binding: a module
    or function that binds its own ``getattr`` does not qualify, an import of
    ``builtins.getattr`` does).  At the ``with`` the local holds whatever
    attribute that run-time string names (``klass = getattr(module, klass)``
    then ``with klass(path) as f:``): no source decides the manager, so there
    is no callee to read.

    Or the local's only binding in that function is the ``as`` target (a name,
    or one name of a flat tuple/list) of an item of one top-level ``with``
    whose own head is formal-rooted (``formal_manager_head``), and the head
    sits inside that ``with``'s body, which never rebinds the local.  At the
    head the local holds what ``__enter__`` returned on an object a caller
    passed (``with c.builder.if_else(p) as (then, otherwise):`` then ``with
    then:``): no frame knows that object's type, so no source decides the
    manager its enter result is.  Anything else returns ``None``.
    """
    from .nodes import Assign, Name, With

    found = _with_item_expr(unit, start_line, start_col)
    if found is None:
        return None
    function, expr = found
    root = _chain_root(expr, operands_admitted=True)
    if root is None:
        return None
    binders = [statement for statement in function.body if _binds(statement, root)]
    if len(binders) != 1:
        return None
    statement = binders[0]
    if isinstance(statement, With):
        if _formal_enter_result_binder(unit, statement, root, expr):
            return expr.segment()
        return None
    if not (
        isinstance(statement, Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], Name)
        and statement.targets[0].id == root
        and _run_time_getattr(unit, statement.value)
    ):
        return None
    if statement.end_lineno >= expr.lineno:
        return None
    return expr.segment()


def call_bound_local_manager_head(unit, start_line: int, start_col: int):
    """``(binder call (line, col), first attribute)`` for a call-bound local head.

    The head is a chain (attribute reads, constant-argument calls, operands on
    the outermost call) whose root is a local of the innermost function around
    the ``with`` -- not a parameter, not declared ``global``/``nonlocal`` --
    whose only binding in that function is one top-level statement ``local =
    <call>``, lexically before the ``with``, and the chain's first step on the
    local is an attribute read.  Top-level statements run in order, so at the
    ``with`` the local holds a value that call returned; which value is for the
    caller to decide from the call (#7742: ``zstd =
    import_optional_dependency("zstandard", errors="ignore")`` then ``with
    zstd.ZstdDecompressor().stream_reader(b"")``).  The binder call's
    (line, col) is its own span's start.  Anything else returns ``None``.
    """
    from .nodes import Assign, Call, Global, Name, Nonlocal

    found = _with_item_expr(unit, start_line, start_col)
    if found is None:
        return None
    function, expr = found
    root = _chain_root(expr, operands_admitted=True)
    if root is None:
        return None
    first = _first_attribute_on(expr, root)
    if first is None:
        return None
    if root in _parameters(function):
        return None
    for node in function.walk():
        if isinstance(node, (Global, Nonlocal)) and root in node.names:
            return None
    binders = [statement for statement in function.body if _binds(statement, root)]
    if len(binders) != 1:
        return None
    statement = binders[0]
    if not (
        isinstance(statement, Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], Name)
        and statement.targets[0].id == root
        and isinstance(statement.value, Call)
    ):
        return None
    if statement.end_lineno >= expr.lineno:
        return None
    call = statement.value
    return (call.lineno, call.col_offset), first


def _first_attribute_on(expr, root: str):
    """The attribute the chain reads directly on its root name, else None."""
    from .nodes import Attribute, Call, Name

    node = expr
    while True:
        if isinstance(node, Attribute):
            if isinstance(node.value, Name) and node.value.id == root:
                return node.attr
            node = node.value
        elif isinstance(node, Call):
            node = node.func
        else:
            return None


def _formal_enter_result_binder(unit, statement, root: str, expr) -> bool:
    """``statement`` binds ``root`` only as a formal-rooted item's enter result."""
    from .nodes import List, Name, Tuple_

    binding_items = [
        item for item in statement.items if root in item.names_bound_here()
    ]
    if len(binding_items) != 1:
        return False
    (item,) = binding_items
    target = item.optional_vars
    names = target.elts if isinstance(target, (Tuple_, List)) else (target,)
    if not all(isinstance(name, Name) for name in names):
        return False
    if [name.id for name in names].count(root) != 1:
        return False
    if any(_binds(item.context_expr, root) for item in statement.items):
        return False
    if any(_binds(body, root) for body in statement.body):
        return False
    if not any(_contains(body, expr) for body in statement.body):
        return False
    head = item.context_expr.line_col_span()
    return formal_manager_head(unit, head.start_line, head.start_col) is not None


def _contains(outer, inner) -> bool:
    """Whether ``inner``'s source span lies inside ``outer``'s."""
    a = outer.line_col_span()
    b = inner.line_col_span()
    return (a.start_line, a.start_col) <= (b.start_line, b.start_col) and (
        b.end_line,
        b.end_col,
    ) <= (a.end_line, a.end_col)


def _run_time_getattr(unit, value) -> bool:
    """``getattr(<object>, <non-constant name>)`` with no default, its callee
    bound to the builtin ``getattr`` (asked of the unit at the callee's own
    coordinate, never read off its spelling)."""
    from .nodes import Call, Constant, LanguageCallee, Name, Starred

    if not (
        isinstance(value, Call)
        and isinstance(value.func, Name)
        and len(value.args) == 2
        and not value.keywords
        and not any(isinstance(arg, Starred) for arg in value.args)
        and not isinstance(value.args[1], Constant)
    ):
        return False
    callee = value.func
    return (
        unit.language_callee_at(callee.id, callee.line_col_span())
        is LanguageCallee.BUILTIN_GETATTR
    )
