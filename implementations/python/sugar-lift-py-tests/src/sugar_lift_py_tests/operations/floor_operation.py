from __future__ import annotations

from typing import ClassVar, Protocol


class FloorOperation(Protocol):
    """Shared dispatch metadata every floor operation carries.

    Operation-specific payloads stay on their concrete classes; this protocol is
    only the typed edge that lets the dispatcher stop erasing the operation to
    ``object`` before invoking the floor.
    """

    method_name: ClassVar[str]

    @property
    def owner(self) -> str: ...

    @property
    def blame(self) -> str: ...
