"""Floor an ``artifact-module-absent`` export by runtime identity (plan Cut 2).

The C module has no authenticated source. The running, pin-authenticated
interpreter's own object is the key: a ``ContextVar`` class or instance, or
a builtin function. Never a name table, never a use-site spelling.
"""

from __future__ import annotations

import importlib
import types

from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedCExtensionCallableValue,
    LanguageOwnedContextVarType,
    LanguageOwnedContextVarValue,
)


def floor_artifact_module_absent_export(resolved):
    """Return a language-owned floor value, or ``None`` to keep the gap."""
    kind = getattr(resolved, "kind", None)
    if kind == "ambiguous-static-export":
        return _floor_ambiguous_c_export(resolved)
    if kind != "artifact-module-absent":
        return None
    module_name = getattr(resolved, "module_name", None)
    exported_name = getattr(resolved, "exported_name", None)
    if not isinstance(module_name, str) or not isinstance(exported_name, str):
        return None
    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, exported_name)
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    import contextvars

    if obj is contextvars.ContextVar:
        return LanguageOwnedContextVarType()
    if isinstance(obj, contextvars.ContextVar):
        return LanguageOwnedContextVarValue(name=obj.name)
    if isinstance(obj, types.BuiltinFunctionType):
        return LanguageOwnedCExtensionCallableValue(
            module_name=module_name, exported_name=exported_name
        )
    if _interpreter_owned_c_class(module_name, module, obj):
        from sugar_lift_py_tests.floor.language_owned_c_type import (
            LanguageOwnedCTypeValue,
        )

        return LanguageOwnedCTypeValue(module_name=module_name, type_name=exported_name)
    return None


def _floor_ambiguous_c_export(resolved):
    """An export the source binds twice, decided by the interpreter: a C builtin.

    ``warnings.py`` binds ``warn`` both by ``from _warnings import warn`` (in a
    ``try``) and by its pure-Python fallback ``def warn`` (in the ``except
    ImportError``); statically that is ``ambiguous-static-export``.  The
    running, pin-authenticated interpreter decides which binding stands, and
    when its object is a builtin function exported by an interpreter-owned
    module, the C import won and no Python body stands behind the name.  It is
    then floored exactly as a C-extension callable: completes with an opaque
    result or raises undetermined.  A Python fallback that won keeps the gap.
    """
    import sys

    from .dependency_export_adapter import _is_stdlib_extension_module

    module_name = getattr(resolved, "module_name", None)
    exported_name = getattr(resolved, "exported_name", None)
    if not isinstance(module_name, str) or not isinstance(exported_name, str):
        return None
    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, exported_name)
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    if not isinstance(obj, types.BuiltinFunctionType):
        return None
    owner = getattr(obj, "__module__", None)
    if not isinstance(owner, str) or (
        owner not in sys.builtin_module_names
        and not _is_stdlib_extension_module(owner)
    ):
        return None
    import warnings

    return LanguageOwnedCExtensionCallableValue(
        module_name=module_name,
        exported_name=exported_name,
        # Runtime identity, not a spelling: the interpreter's own warn.
        warning_occurrence=obj is warnings.warn,
    )


_PY_TPFLAGS_HEAPTYPE = 1 << 9


def _interpreter_owned_c_class(module_name, module, obj) -> bool:
    """``obj`` is a C type that an interpreter-owned module exports.

    Runtime identity, never a name table: the module is built in or a stdlib
    ``lib-dynload`` extension, ``obj`` is a class, and none of its own
    attributes is a Python function, so no Python body stands behind it.  A
    heap type (``_io.TextIOWrapper``) qualifies through the member check.  A
    class statement always makes a heap type, so a static type is C by the
    interpreter's own testimony; it qualifies when its C ``tp_name`` is
    dotted, i.e. it names the extension module that declares it
    (``_decimal``'s ``Decimal`` reports ``decimal``).  A static type with an
    undotted ``tp_name`` reports ``builtins``: it is a core language type
    (``int``) with its own floor, not an opaque C-library type.  This is the
    type rule; the C-function rule above keys on ``builtin_function_or_method``
    and never admits a class.
    """
    import sys

    from .dependency_export_adapter import _is_stdlib_extension_module

    if not isinstance(obj, type):
        return False
    if not obj.__flags__ & _PY_TPFLAGS_HEAPTYPE and obj.__module__ == "builtins":
        return False
    if module_name not in sys.builtin_module_names and not _is_stdlib_extension_module(
        module_name
    ):
        return False
    if getattr(module, "__file__", None) is not None and not str(
        module.__file__
    ).endswith((".so", ".pyd")):
        return False
    return not any(
        isinstance(member, (types.FunctionType, staticmethod, classmethod))
        for member in vars(obj).values()
    )


def floor_language_owned_import_use(imported, receipt, *, graph, session):
    """Floor a C-export value-use, including ``ContextVar.set`` / ``reset``.

    ``foo.set`` is a method on the floored instance, not a module export.
    """
    from sugar_lift_py_tests.floor.language_owned_contextvar import (
        LanguageOwnedContextVarMethodValue,
        LanguageOwnedContextVarValue,
    )

    direct = floor_artifact_module_absent_export(imported)
    if direct is not None:
        return direct
    if getattr(imported, "kind", None) != "target-outside-binding":
        return None
    path = list(receipt.use.get("exportedMemberPath") or ())
    if not path or path[-1] not in {"set", "reset", "get"}:
        return None
    try:
        target = receipt.import_binding.to_value()["target"]
        bound_path = target["exportedPath"]
        identity = target["moduleIdentity"]
        if identity["kind"] == "authenticated-python-module":
            module_name = identity["moduleName"]
        elif identity["kind"] == "unavailable-python-module":
            module_name = identity["name"]
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(bound_path, list) or len(bound_path) != 1:
        return None
    from .dependency_export_adapter import resolve_export

    prefix = resolve_export(
        graph,
        receipt.import_binding.cid,
        module_name,
        bound_path[0],
        (),
        frozenset(),
        session=session,
    )
    variable = floor_artifact_module_absent_export(prefix)
    if variable is None:
        variable = floor_source_contextvar_export(prefix, graph=graph)
    if not isinstance(variable, LanguageOwnedContextVarValue):
        return None
    return LanguageOwnedContextVarMethodValue(variable=variable, method=path[-1])


def floor_source_contextvar_export(resolved, *, graph):
    """A module-level ``NAME = ContextVar("n"[, default=...])`` in source.

    The export door classes a module-level assignment as ``dynamic-export``.
    When the defining module binds ``NAME`` exactly once, at module level, to a
    call of ``ContextVar`` that the module binds exactly once by ``from
    contextvars import ContextVar``, the export is that language-owned
    ContextVar: the call is applied through ``LanguageOwnedContextVarType``,
    the one law for constructing one.  Any other shape keeps the gap.
    """
    import ast

    if getattr(resolved, "kind", None) != "dynamic-export":
        return None
    module_name = getattr(resolved, "module_name", None)
    exported_name = getattr(resolved, "exported_name", None)
    module = getattr(graph, "modules", {}).get(module_name)
    if module is None or not isinstance(exported_name, str):
        return None
    try:
        tree = ast.parse(module.source)
    except SyntaxError:
        return None
    return contextvar_bound_in_tree(tree, exported_name)


def contextvar_bound_in_tree(tree, name):
    """The language-owned ContextVar ``name`` denotes in module ``tree``.

    ``name`` is bound exactly once, at module level, to ``ContextVar("n"[,
    default=...])`` with ``ContextVar`` bound exactly once by ``from
    contextvars import ContextVar``, or to ``m.ContextVar(...)`` with ``m``
    bound exactly once by ``import contextvars [as m]``; the call is applied through
    ``LanguageOwnedContextVarType``.  Any other shape is ``None``.
    """
    import ast

    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor.language_owned_contextvar import (
        LanguageOwnedContextVarType,
        LanguageOwnedContextVarValue,
    )
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.outcome import Complete

    call = _sole_module_assignment_call(tree, name)
    if call is None:
        return None
    if isinstance(call.func, ast.Name):
        if not _bound_once_by_contextvars_import(tree, call.func.id):
            return None
    elif (
        # ``import contextvars`` then ``contextvars.ContextVar(...)``: the
        # same class reached through the module the name is bound to once.
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "ContextVar"
        and isinstance(call.func.value, ast.Name)
    ):
        if not _bound_once_to_contextvars_module(tree, call.func.value.id):
            return None
    else:
        return None
    if len(call.args) != 1 or not (
        isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
    ):
        return None
    if any(keyword.arg is None for keyword in call.keywords):
        return None
    keyword_names = tuple(keyword.arg for keyword in call.keywords)
    if keyword_names not in ((), ("default",)):
        return None
    from sugar_lift_py_tests.floor.term_value import TermValue

    # The default's value is never read by set/reset; it rides as an opaque
    # actual so the constructor law sees the call's real shape.
    outcome = LanguageOwnedContextVarType().callable_application_with(
        CallableApplication(
            arguments=(
                StringValue(call.args[0].value),
                *(TermValue(None) for _ in keyword_names),
            ),
            keyword_names=keyword_names,
            site=None,
            owner="floor_source_contextvar_export",
        ),
        None,
    )
    if isinstance(outcome, Complete) and isinstance(
        outcome.value, LanguageOwnedContextVarValue
    ):
        return outcome.value
    return None


def source_contextvar_global_read(source, name, line, col):
    """The ContextVar a function body's global read of ``name`` denotes.

    A ``Name`` read at (``line``, ``col``) inside a ``def`` or ``lambda`` of
    ``source``, which nothing in that function binds, reads the module global;
    when the module binds it by the ContextVar law above
    (``contextvar_bound_in_tree``), the read is that ContextVar.  Any binding
    of ``name`` anywhere else in the module (a local, a parameter, a
    ``global``) breaks the exactly-once shape and keeps ``None``.
    """
    if "ContextVar" not in source:
        return None
    tree, functions = _parsed_module(source)
    enclosing = [
        params
        for start_line, start_col, end_line, end_col, params in functions
        if (start_line, start_col) <= (line, col) <= (end_line, end_col)
    ]
    if tree is None or not enclosing or any(name in params for params in enclosing):
        return None
    return contextvar_bound_in_tree(tree, name)


_PARSED_MODULES: dict = {}


def _parsed_module(source):
    import ast

    cached = _PARSED_MODULES.get(source)
    if cached is not None:
        return cached
    try:
        tree = ast.parse(source)
    except SyntaxError:
        cached = (None, ())
    else:
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = node.args
                params = frozenset(
                    argument.arg
                    for argument in (
                        *arguments.posonlyargs,
                        *arguments.args,
                        *arguments.kwonlyargs,
                        *(a for a in (arguments.vararg, arguments.kwarg) if a),
                    )
                )
                functions.append(
                    (
                        node.lineno,
                        node.col_offset,
                        node.end_lineno,
                        node.end_col_offset,
                        params,
                    )
                )
        cached = (tree, tuple(functions))
    if len(_PARSED_MODULES) > 16:
        _PARSED_MODULES.clear()
    _PARSED_MODULES[source] = cached
    return cached


def _module_level_bindings(tree, name):
    """Every statement in ``tree`` that binds ``name`` in module scope."""
    import ast

    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return None
        if isinstance(node, ast.Name) and node.id == name and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            found.append(node)
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and node.name == name:
            found.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    return None
                local = alias.asname or alias.name.split(".")[0]
                if local == name:
                    found.append(node)
    return found


def _sole_module_assignment_call(tree, name):
    import ast

    bindings = _module_level_bindings(tree, name)
    if bindings is None or len(bindings) != 1:
        return None
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and statement.targets[0] is bindings[0]
            and isinstance(statement.value, ast.Call)
        ):
            return statement.value
        if (
            isinstance(statement, ast.AnnAssign)
            and statement.target is bindings[0]
            and isinstance(statement.value, ast.Call)
        ):
            return statement.value
    return None


def _bound_once_to_contextvars_module(tree, name):
    """``name`` is bound exactly once, by a module-level ``import contextvars``."""
    import ast

    bindings = _module_level_bindings(tree, name)
    if bindings is None or len(bindings) != 1:
        return False
    (binding,) = bindings
    return (
        isinstance(binding, ast.Import)
        and binding in tree.body
        and any(
            alias.name == "contextvars" and (alias.asname or alias.name) == name
            for alias in binding.names
        )
    )


def _bound_once_by_contextvars_import(tree, name):
    import ast

    bindings = _module_level_bindings(tree, name)
    if bindings is None or len(bindings) != 1:
        return False
    (binding,) = bindings
    return (
        isinstance(binding, ast.ImportFrom)
        and binding in tree.body
        and binding.module == "contextvars"
        and binding.level == 0
        and any(
            alias.name == "ContextVar" and (alias.asname or alias.name) == name
            for alias in binding.names
        )
    )
