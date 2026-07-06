from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.factory.factory_gap_info import (
    GapKind,
    GapLocus,
    gap_kind_label,
    gap_locus_label,
)


@dataclass(frozen=True)
class FactoryGapEffect:
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    gap_kind: GapKind
    gap_locus: GapLocus

    def __post_init__(self) -> None:
        # Static typing says these are always GapKind/GapLocus; the runtime guard
        # stays because construction still happens from untyped call sites
        # (kwargs unpacked from dicts, vendor-facing constructors) where the
        # static type is a promise, not a proof. Boundary law, not dead code.
        if not isinstance(
            self.gap_kind, GapKind
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(
                "FactoryGapEffect.gap_kind must be GapKind: owner=FactoryGapEffect "
                f"shape={type(self.gap_kind).__name__} replacement=GapKind.FLOOR"
            )
        if not isinstance(
            self.gap_locus, GapLocus
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(
                "FactoryGapEffect.gap_locus must be GapLocus: owner=FactoryGapEffect "
                f"shape={type(self.gap_locus).__name__} "
                "replacement=GapLocus.CONSTRUCTION"
            )

    @classmethod
    def from_gap(cls, gap: FactoryGap) -> FactoryGapEffect:
        info = gap.info
        return cls(
            owner=info.owner,
            blame=info.blame,
            observed=info.observed,
            requested=info.requested,
            fix=info.fix,
            gap_kind=info.gap_kind,
            gap_locus=info.gap_locus,
        )

    @property
    def reason(self) -> str:
        return (
            f"write more {gap_kind_label(self.gap_kind)} for this "
            f"{gap_locus_label(self.gap_locus)}: "
            f"owner={self.owner} blame={self.blame} observed={self.observed} "
            f"requested={self.requested} fix={self.fix}"
        )
