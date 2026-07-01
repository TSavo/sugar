"""Shared recognition of the verify-facing AUTHORING decorators.

The Python peer of Go's `//sugar:boundary(...)` / `//sugar:sugar(...)`
doc-comment pragma (PR #1445). A library author declares that a function's body
is a contract they want discharged with::

    @sugar.boundary(concept="concept:mul")   # or @boundary(...)
    def double(x: int) -> int:
        return x * 2

These decorators are DECLARATIVE metadata (which concept/boundary the function
realizes), NOT behavioral wrappers, so the source lifter SKIPS them when
deciding whether a function is "decorated" -- it lifts the body underneath.
This is distinct from `@sugar.bind(concept=, library=)` (the library-binding
catalog decorator the bind lifter consumes); `@sugar`/`@boundary` here is the
verify-facing authoring declaration.
"""

from __future__ import annotations

import ast

_AUTHORING_NAMES = {"boundary", "sugar"}


def authoring_kind(decorator: ast.expr) -> str | None:
    """Return "boundary"/"sugar" if `decorator` is a verify-facing authoring
    declaration, else None. Matches `@boundary(...)`, `@sugar(...)`,
    `@sugar.boundary(...)`, `@sugar.sugar(...)` and their bare
    (non-call) forms. Does NOT match `@sugar.bind(...)` (the library-binding
    decorator: its callee is `Attribute(attr="bind")`)."""
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(func, ast.Name):
        return func.id if func.id in _AUTHORING_NAMES else None
    if isinstance(func, ast.Attribute) and func.attr in _AUTHORING_NAMES:
        value = func.value
        if isinstance(value, ast.Name) and value.id == "sugar":
            return func.attr
    return None


def is_authoring_decorator(decorator: ast.expr) -> bool:
    return authoring_kind(decorator) is not None


def authoring_declaration(decorator: ast.expr) -> dict[str, str] | None:
    """Parse `{kind, concept?, library?}` from a verify-facing authoring
    decorator, or None if it is not one."""
    kind = authoring_kind(decorator)
    if kind is None:
        return None
    decl: dict[str, str] = {"kind": kind}
    if isinstance(decorator, ast.Call):
        for keyword in decorator.keywords:
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                if keyword.arg == "concept":
                    decl["concept"] = keyword.value.value
                elif keyword.arg == "library":
                    decl["library"] = keyword.value.value
    return decl
