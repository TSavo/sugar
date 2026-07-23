from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectationNotMetEffect:
    effect_kind: str
    site: object = None

    @property
    def reason(self) -> str:
        return f"expected {self.effect_kind} effect was not observed"
