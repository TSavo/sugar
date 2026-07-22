from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WarningEffect:
    """A non-halting Python warning observation.

    Category is independently observable from message.  ``message`` remains
    ``None`` until an authenticated producer carries it; absence is not an
    empty message and cannot discharge a message-pattern obligation.
    """

    category_name: str
    message: str | None = None
    blame: str | None = None

    @property
    def reason(self) -> str:
        locus = f" at {self.blame}" if self.blame is not None else ""
        return (
            f"warning {self.category_name}{locus}: a non-halting Python warning effect"
        )
