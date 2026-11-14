from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .raise_effect import RaiseEffect


@dataclass(frozen=True)
class NameErrorEffect(RaiseEffect):
    """Deterministic Python halt caused by an unbound source name.

    Construct through ``NameErrorEffect.at``: like every authenticated raise it
    carries the builtins exception identity and an authenticated locus. Which
    builtin is decided by the scope of the read, never assumed: an unbound
    function local raises ``UnboundLocalError`` (a ``NameError`` subclass);
    a module- or class-scope name raises ``NameError``.
    """

    name: str = ""
    site: object = field(default=None, compare=False)

    @classmethod
    def at(cls, *, name: str, site) -> "NameErrorEffect":
        from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

        exception_name = _unbound_read_exception_name(name, site)
        coordinate, mro = _builtin_exception_identity(exception_name)
        locus = f"{site.filename}:{site.line}:{site.col}"
        return cls(
            exception_type_coordinate=coordinate,
            occurrence=locus,
            exception_name=exception_name,
            exception_type_mro=mro,
            producer_node_owner="NameErrorEffect",
            name=name,
            site=site,
        )

    def __post_init__(self) -> None:
        locus = f"{self.site.filename}:{self.site.line}:{self.site.col}"
        source = getattr(getattr(self.site, "unit", None), "source", None)
        object.__setattr__(self, "blame", locus)
        object.__setattr__(
            self,
            "source_sha256",
            (
                hashlib.sha256(source.encode()).hexdigest()
                if isinstance(source, str)
                else None
            ),
        )
        super().__post_init__()

    @property
    def reason(self) -> str:
        return (
            f"{self.exception_name or 'NameError'} for unbound name "
            f"{self.name!r} at {self.blame}"
        )


_SCOPE_KINDS = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "Lambda")


def _unbound_read_exception_name(name: str, site) -> str:
    """``UnboundLocalError`` for an unbound function local, else ``NameError``.

    The scope is the innermost function, class, or lambda whose BODY contains
    the read occurrence (decorators, defaults, and bases are evaluated in the
    enclosing scope). A function scope decides by its own symbol table.  A
    unit with no typed tree refuses by name (``_require_typed_module``).
    """
    unit = site.unit
    module = unit._require_typed_module("NameErrorEffect.at", blame=site)
    span = site.span
    innermost = None
    innermost_start = -1
    for node in module.walk():
        if node.kind not in _SCOPE_KINDS:
            continue
        body = node.body if node.kind != "Lambda" else (node.body,)
        if not body:
            continue
        start = body[0].fragment.span.start
        end = body[-1].fragment.span.end
        if start <= span.start and span.end <= end and start > innermost_start:
            innermost, innermost_start = node, start
    if innermost is None or innermost.kind in ("ClassDef", "Lambda"):
        return "NameError"
    table = unit.function_symtable(innermost.name, innermost.line_col_span().start_line)
    # Parameters are locals too: ``del a`` then ``a`` is UnboundLocalError.
    return "UnboundLocalError" if name in table.get_locals() else "NameError"
