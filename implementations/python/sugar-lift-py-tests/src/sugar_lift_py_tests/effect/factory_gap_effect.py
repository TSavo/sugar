from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory.factory_gap import FactoryGap


@dataclass(frozen=True)
class FactoryGapEffect:
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    gap_kind: str
    gap_locus: str

    @classmethod
    def from_gap(cls, gap: FactoryGap) -> FactoryGapEffect:
        info = gap.info
        return cls(
            owner=str(info.get("owner", "FactoryGap")),
            blame=str(info.get("blame", "")),
            observed=str(info.get("observed", "")),
            requested=str(info.get("requested", "")),
            fix=str(info.get("fix", "")),
            gap_kind=str(info.get("gap_kind", "Sugar")),
            gap_locus=str(info.get("gap_locus", "AST")),
        )

    @property
    def reason(self) -> str:
        return (
            f"write more {self.gap_kind} for this {self.gap_locus}: "
            f"owner={self.owner} blame={self.blame} observed={self.observed} "
            f"requested={self.requested} fix={self.fix}"
        )
