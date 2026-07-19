"""Implementation-preserving decorator contracts.

Authenticated native exports whose decorator application leaves the decorated
FunctionCallable body as the public-API implementation (metadata copy only).

Two authentication doors (both structural; neither is a bare-name logo pass):

1. **Qualified target / stamped native shape** — CallSugar/MethodCallSugar
   stamps ``CallSiteValue.native_shape`` from an ImportAlias import coordinate
   recognized by ``recognize_native_decorator``.
2. **Decorator Call site + defining-module imports** — when the floor value
   carries only a bare method name (nested dig without import_aliases), the
   decorator AST site still names ``functools.wraps`` / ``wraps`` and the
   defining module's ``import functools`` / ``from functools import wraps``
   warrant is re-read from ``site.source``.

Lives under ``recognition/`` — factory stays select-or-panic only.
"""

from __future__ import annotations

from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    recognize_native_decorator,
)


def decorator_value_preserves_implementation(decorator) -> bool:
    """True when a reduced decorator operand is an implementation-preserving factory."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    if not isinstance(decorator, CallSiteValue):
        return False
    if decorator.native_shape is NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR:
        return True
    if recognize_native_decorator(decorator.target_name) is (
        NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR
    ):
        return True
    return call_site_preserves_implementation(decorator.site)


def call_site_preserves_implementation(decorator_site) -> bool:
    """Authenticate a decorator Call AST against defining-module imports.

    Structural + source-authenticated only. A local or third-party ``wraps``
    without a functools import warrant stays unowned.
    """
    if decorator_site is None:
        return False
    try:
        if decorator_site.observed != "Call":
            return False
    except (AttributeError, TypeError):
        return False
    try:
        receiver = decorator_site.call_func()
    except (AttributeError, TypeError):
        return False
    if receiver is None:
        return False
    try:
        dotted = receiver.dotted_expr_name()
    except (AttributeError, TypeError):
        return False
    if dotted is None:
        return False

    # Never trust Attribute spelling alone (``functools.wraps`` after
    # ``import lookalike as functools``). Re-bind the Call head through the
    # defining module's import warrants, then recognize the resolved export.
    source = getattr(decorator_site, "source", None)
    filename = getattr(decorator_site, "filename", None) or ""
    if not source:
        return False

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        root = SourceFragment.from_source(source, filename)
    except (SyntaxError, TypeError, ValueError):
        return False

    authenticated_names: set[str] = set()
    authenticated_modules: dict[str, str] = {}
    try:
        declarations = [
            declaration
            for fragment in root.fragments()
            for declaration in fragment.statements()
        ]
    except (AttributeError, TypeError):
        return False

    for declaration in declarations:
        try:
            observed = declaration.observed
        except (AttributeError, TypeError):
            continue
        if observed == "ImportFrom":
            try:
                module = declaration.importfrom_module()
                names = declaration.importfrom_names()
            except (AttributeError, TypeError):
                continue
            if module is None:
                continue
            for imported, alias in names:
                qualified = f"{module}.{imported}"
                if recognize_native_decorator(qualified) is (
                    NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR
                ):
                    authenticated_names.add(alias or imported)
        elif observed == "Import":
            try:
                names = declaration.import_names()
            except (AttributeError, TypeError):
                continue
            for imported, alias in names:
                head = imported.split(".", 1)[0]
                authenticated_modules[alias or head] = imported

    if dotted in authenticated_names:
        return True
    head, separator, tail = dotted.partition(".")
    if not separator:
        return False
    module = authenticated_modules.get(head)
    if module is None:
        return False
    export_module = module
    export_name = tail
    if "." in tail:
        nested, _, export_name = tail.rpartition(".")
        export_module = f"{module}.{nested}"
    qualified = f"{export_module}.{export_name}"
    return (
        recognize_native_decorator(qualified)
        is NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR
    )
