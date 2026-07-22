from __future__ import annotations

from typing import NoReturn

from sugar_lift_py_tests.gap.panic import factory_panic
from sugar_lift_py_tests.gap.info import FactoryGapInfo, GapKind, GapLocus


def proofir_construction_gap(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    info = FactoryGapInfo(
        owner=owner,
        blame="proofir-construction-law",
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.PROOFIR,
        gap_locus=GapLocus.CONSTRUCTION_LAW,
    )
    factory_panic(info)
