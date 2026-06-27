from __future__ import annotations

from dataclasses import dataclass

from .sugar_claim import SugarClaim


@dataclass(frozen=True)
class SugarCandidate:
    claim: SugarClaim

    @property
    def name(self) -> str:
        return self.claim.name
