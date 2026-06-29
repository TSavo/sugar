from __future__ import annotations

from enum import Enum


class SugarRole(str, Enum):
    TERM = "term"
    # An inert statement -- present in the source, no first-order logic, no scope.
    # The factory composes a Support sugar so the audit records it (it is never a
    # silent skip and never a refusal).
    SUPPORT = "support"

    def __str__(self) -> str:
        return self.value
