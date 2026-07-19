"""Authenticated support warrants for callee-universe coverage and ownership."""

from __future__ import annotations

import ast
from enum import Enum, auto

from sugar_lift_python_source.source_tables import locate_parsed_node, parsed_parents
from sugar_lift_py_tests.recognition.visible_declarations import (
    declaration_is_function_local,
    lexical_function_bindings,
    visible_declarations,
)


class CalleeUniverseSupport(Enum):
    """A native call coordinate whose universe is carried by existing support."""

    NUMPY_ISSUBDTYPE = auto()
    NUMPY_ALLCLOSE = auto()
    NUMPY_CAN_CAST = auto()
    NUMPY_ISNAN = auto()
    NUMPY_ALL = auto()


_IMPORTED_SUPPORT = {
    "numpy.issubdtype": CalleeUniverseSupport.NUMPY_ISSUBDTYPE,
    "numpy.allclose": CalleeUniverseSupport.NUMPY_ALLCLOSE,
    "numpy.can_cast": CalleeUniverseSupport.NUMPY_CAN_CAST,
    "numpy.isnan": CalleeUniverseSupport.NUMPY_ISNAN,
    "numpy.all": CalleeUniverseSupport.NUMPY_ALL,
}

_BUILTIN_COORDINATES = frozenset({"type", "dtype", "all"})


def recognize_callee_universe(
    target: str | None = None,
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
    identity = imported_call_identity(site)
    if identity is None:
        return None
    support = _IMPORTED_SUPPORT.get(identity)
    if support is None:
        return None
    if target is not None and target != f"call:{identity}":
        return None
    return support


class CalleeUniverseRecognition:
    """Resolve a call's authenticated source-bound callee coordinate."""

    @classmethod
    def coordinate(cls, site) -> str | None:
        if site is None or site.observed != "Call" or site.call_has_keywords():
            return None

        receiver = site.call_receiver()
        if receiver is not None:
            if not site.source:
                return None
            imported = imported_call_identity(site)
            if imported in _IMPORTED_SUPPORT:
                return imported
            return cls._method_coordinate(site, receiver)

        target = site.call_target_name()
        if target is None:
            return None
        if target in _BUILTIN_COORDINATES:
            # Without source there is no evidence of shadowing; keep the bare
            # builtin warrant. With source, parameters and local rebinds revoke.
            if not site.source:
                return target
            return target if cls._name_is_unshadowed(site, target) else None

        if not site.source:
            return None
        return imported_call_identity(site)

    @classmethod
    def _name_is_unshadowed(cls, site, name: str) -> bool:
        """Bare builtin names lose their warrant under parameters or local rebinds."""

        _declarations, shadowed_parameters = visible_declarations(site)
        if name in shadowed_parameters:
            return False
        if name in lexical_function_bindings(site):
            # A function-local binding of ``type``/``dtype``/``all`` (parameter
            # or later assignment) is never the builtin coordinate.
            return False
        # Module-level assignment before the site also revokes.
        for declaration in _declarations:
            if name in declaration.stored_or_deleted_names():
                return False
        return True

    @classmethod
    def _method_coordinate(cls, site, receiver) -> str | None:
        """Authenticate ``self.attr(...)`` only for the class instance receiver.

        Arbitrary parameters named something other than the method's instance
        parameter do not inherit the class attribute's converter warrant.
        Preceding reassignment of the instance parameter also revokes.
        """

        if receiver.observed != "Name":
            return None
        attr = site.call_target_name()
        if attr is None:
            return None
        receiver_name = receiver.name_id()
        method, class_def = _enclosing_method_and_class(site)
        if method is None or class_def is None:
            return None
        instance_param = _instance_parameter_name(method)
        if instance_param is None or receiver_name != instance_param:
            return None
        if _name_reassigned_before(site, receiver_name):
            return None
        return _class_attribute_coordinate(class_def, attr, site)


def imported_call_identity(site) -> str | None:
    """Resolve a plain or dotted call target to its import/assignment identity.

    Later function-local rebinding (including assignments after the call site)
    revokes outer import warrants, matching Python's scope-wide local binding.
    Parameters always revoke.
    """

    if site is None or site.observed != "Call":
        return None
    function = site.call_func()
    dotted = function.dotted_expr_name()
    if dotted is None:
        return None

    declarations, shadowed_parameters = visible_declarations(site)
    imported: dict[str, tuple[str, bool]] = {}
    assigned: dict[str, str | None] = {}
    for declaration in declarations:
        function_local = declaration_is_function_local(site, declaration)
        if declaration.observed == "ImportFrom":
            module = declaration.importfrom_module()
            if module is not None:
                for name, alias in declaration.importfrom_names():
                    bound = alias or name
                    imported[bound] = (f"{module}.{name}", function_local)
                    assigned.pop(bound, None)
            continue
        if declaration.observed == "Import":
            for name, alias in declaration.import_names():
                bound = alias or name.split(".", 1)[0]
                imported[bound] = (
                    name if alias is not None else bound,
                    function_local,
                )
                assigned.pop(bound, None)
            continue
        stored = declaration.stored_or_deleted_names()
        for bound in stored:
            imported.pop(bound, None)
        if declaration.observed != "Assign" or len(stored) != 1:
            for bound in stored:
                assigned[bound] = None
            continue
        bound = next(iter(stored))
        value_dotted = declaration.assign_value().dotted_expr_name()
        if value_dotted is None:
            assigned[bound] = None
            continue
        value_head, value_sep, value_tail = value_dotted.partition(".")
        if value_head in shadowed_parameters:
            assigned[bound] = None
            continue
        origin_entry = imported.get(value_head)
        if origin_entry is None:
            assigned[bound] = None
            continue
        origin, origin_local = origin_entry
        if value_head in lexical_function_bindings(site) and not origin_local:
            assigned[bound] = None
            continue
        assigned[bound] = origin if not value_sep else f"{origin}.{value_tail}"

    head, separator, tail = dotted.partition(".")
    if head in shadowed_parameters:
        return None

    # Prefer explicit assignment identity for the leaf name (``conv = mt.x``).
    if not separator and head in assigned:
        return assigned[head]

    resolved = imported.get(head)
    if resolved is None:
        return None
    origin, function_local = resolved
    if head in lexical_function_bindings(site) and not function_local:
        return None
    return origin if not separator else f"{origin}.{tail}"


def _enclosing_method_and_class(site):
    path = _source_path(site)
    if path is None:
        return None, None
    method = None
    class_def = None
    for node in reversed(path):
        if method is None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method = node
            continue
        if method is not None and isinstance(node, ast.ClassDef):
            class_def = node
            break
    return method, class_def


def _instance_parameter_name(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    args = method.args
    positional = [*args.posonlyargs, *args.args]
    if not positional:
        return None
    return positional[0].arg


def _name_reassigned_before(site, name: str) -> bool:
    """True when a preceding statement in the same function stores ``name``."""

    declarations, _shadowed = visible_declarations(site)
    for declaration in declarations:
        if not declaration_is_function_local(site, declaration):
            continue
        if declaration.observed in {"Import", "ImportFrom"}:
            continue
        if name in declaration.stored_or_deleted_names():
            return True
    return False


def _class_attribute_coordinate(class_def: ast.ClassDef, attr: str, site) -> str | None:
    """Resolve ``attr`` on a class body to an imported coordinate, if any."""

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    source = site.source
    filename = site.filename or ""
    imported: dict[str, str] = {}
    coordinate: str | None = None
    for statement in class_def.body:
        fragment = SourceFragment.from_node(statement, filename, source=source)
        if fragment.observed == "ImportFrom":
            module = fragment.importfrom_module()
            if module is None:
                continue
            for name, alias in fragment.importfrom_names():
                imported[alias or name] = f"{module}.{name}"
            continue
        if fragment.observed == "Import":
            for name, alias in fragment.import_names():
                bound = alias or name.split(".", 1)[0]
                imported[bound] = name if alias is not None else bound
            continue
        if fragment.observed != "Assign":
            continue
        stored = fragment.stored_or_deleted_names()
        if attr not in stored:
            continue
        if len(stored) != 1:
            coordinate = None
            continue
        value = fragment.assign_value()
        dotted = value.dotted_expr_name()
        if dotted is None:
            coordinate = None
            continue
        head, separator, tail = dotted.partition(".")
        origin = imported.get(head)
        if origin is None:
            # Module-level imports visible at the class site still count.
            origin = _module_import_origin(site, head)
        if origin is None:
            coordinate = None
            continue
        coordinate = origin if not separator else f"{origin}.{tail}"
    return coordinate


def _module_import_origin(site, head: str) -> str | None:
    declarations, shadowed = visible_declarations(site)
    if head in shadowed:
        return None
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
    resolved = imported.get(head)
    if resolved is None:
        return None
    origin, function_local = resolved
    if head in lexical_function_bindings(site) and not function_local:
        return None
    return origin


def _source_path(statement):
    source = getattr(statement, "source", None)
    if not source:
        return None
    parsed = parsed_parents(source)
    if parsed is None:
        return None
    _tree, parents = parsed
    target = locate_parsed_node(
        source, type(statement.node), statement.line, statement.col
    )
    if target is None:
        return None
    path = [target]
    while path[-1] in parents:
        path.append(parents[path[-1]])
    path.reverse()
    return tuple(path)


__all__ = [
    "CalleeUniverseRecognition",
    "CalleeUniverseSupport",
    "imported_call_identity",
    "recognize_callee_universe",
]
