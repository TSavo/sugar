from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MethodCallOperation:
    """Exact receiver-owned method dispatch request.

    The sugar owns evaluation order and supplies already-reduced positional
    values.  The receiver Floor owns whether that method is foldable, symbolic,
    or loud; this product carries no spelling-derived return semantics.
    """

    name: str
    arguments: tuple[object, ...]
    owner: str
    blame: object

    method_name = "call_method_with"

    def __post_init__(self) -> None:
        if not self.name:
            raise TypeError("MethodCallOperation requires a method name")
