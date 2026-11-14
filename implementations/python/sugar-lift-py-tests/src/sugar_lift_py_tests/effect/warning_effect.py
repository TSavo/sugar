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
    # The source fragment of the ``warnings.warn(...)`` call the warning was
    # observed at (#7766): where it occurred, and so part of which warning it
    # is (a warning has no other occurrence).  ``None`` when no producer
    # carried one.
    site: object | None = None
    # Source-authenticated identity of the warning category.  A spelling is
    # diagnostic only; completed-face assertion routing requires this term and
    # refuses when the producer did not construct it.
    category_identity: object | None = None

    @property
    def reason(self) -> str:
        locus = f" at {self.site}" if self.site is not None else ""
        return (
            f"warning {self.category_name}{locus}: a non-halting Python warning effect"
        )
