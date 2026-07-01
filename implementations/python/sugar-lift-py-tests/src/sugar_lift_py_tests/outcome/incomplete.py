from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Incomplete:
    effect: object

    @property
    def reason(self) -> str:
        return getattr(self.effect, "reason", str(self.effect))
