from __future__ import annotations

from typing import NoReturn

from sugar_lift_py_tests.gap.panic import construction_panic
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus


def proofir_construction_gap(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    info = ConstructionGap(
        owner=owner,
        blame="proofir-construction-law",
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.PROOFIR,
        gap_locus=GapLocus.CONSTRUCTION_LAW,
    )
    construction_panic(info)
