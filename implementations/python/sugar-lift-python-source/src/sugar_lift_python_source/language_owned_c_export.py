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
    if getattr(resolved, "kind", None) != "artifact-module-absent":
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
    return None


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

    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.outcome import Complete

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
    call = _sole_module_assignment_call(tree, exported_name)
    if call is None or not isinstance(call.func, ast.Name):
        return None
    if not _bound_once_by_contextvars_import(tree, call.func.id):
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
