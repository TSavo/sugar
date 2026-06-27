from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .sugar_candidate import SugarCandidate
from .sugar_claim import SugarClaim
from .sugar_role import SugarRole


@dataclass(frozen=True)
class SugarCatalog:
    claims: Iterable[SugarClaim] = ()

    def candidates_for(self, role: SugarRole, site) -> List[SugarCandidate]:
        candidates = []
        for claim in self.claims:
            if claim.role == role and claim.owns(site):
                candidates.append(SugarCandidate(claim))
        return candidates
