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
    if not path or path[-1] not in {"set", "reset"}:
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
    if not isinstance(variable, LanguageOwnedContextVarValue):
        return None
    return LanguageOwnedContextVarMethodValue(variable=variable, method=path[-1])
