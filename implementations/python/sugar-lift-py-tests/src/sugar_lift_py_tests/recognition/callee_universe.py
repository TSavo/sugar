"""Authenticated support warrants for callee-universe coverage."""

from __future__ import annotations

from enum import Enum, auto

from sugar_lift_py_tests.recognition.visible_declarations import (
    declaration_is_function_local,
    lexical_function_bindings,
    visible_declarations,
)


class CalleeUniverseSupport(Enum):
    """A native call coordinate whose universe is carried by existing support."""

    NUMPY_ISSUBDTYPE = auto()
    NUMPY_ALLCLOSE = auto()


_IMPORTED_SUPPORT = {
    "numpy.issubdtype": CalleeUniverseSupport.NUMPY_ISSUBDTYPE,
    "numpy.allclose": CalleeUniverseSupport.NUMPY_ALLCLOSE,
}


def recognize_callee_universe(
    target: str,
    *,
    site,
) -> CalleeUniverseSupport | None:
    """Recognize one exact support family from structural/import testimony.

    NumPy support is accepted only when the source call's lexical import
    identity still resolves to an exact registered target. Parameters and
    assignments revoke the import warrant.
    """

    if site is None:
        return None
    identity = _imported_call_identity(site)
    if identity is None:
        return None
    support = _IMPORTED_SUPPORT.get(identity)
    if support is None or target != f"call:{identity}":
        return None
    return support


def _imported_call_identity(site) -> str | None:
    function = site.call_func()
    dotted = function.dotted_expr_name()
    if dotted is None:
        return None

    declarations, shadowed_parameters = visible_declarations(site)
    imported: dict[str, tuple[str, bool]] = {}
    for declaration in declarations:
        function_local = declaration_is_function_local(site, declaration)
        if declaration.observed == "ImportFrom":
            module = declaration.importfrom_module()
            if module is not None:
                for name, alias in declaration.importfrom_names():
                    imported[alias or name] = (f"{module}.{name}", function_local)
            continue
        if declaration.observed == "Import":
            for name, alias in declaration.import_names():
                bound = alias or name.split(".", 1)[0]
                imported[bound] = (
                    name if alias is not None else bound,
                    function_local,
                )
            continue
        for bound in declaration.stored_or_deleted_names():
            imported.pop(bound, None)

    head, separator, tail = dotted.partition(".")
    if head in shadowed_parameters:
        return None
    resolved = imported.get(head)
    if resolved is None:
        return None
    origin, function_local = resolved
    if head in lexical_function_bindings(site) and not function_local:
        return None
    return origin if not separator else f"{origin}.{tail}"


__all__ = [
    "CalleeUniverseSupport",
    "recognize_callee_universe",
]
