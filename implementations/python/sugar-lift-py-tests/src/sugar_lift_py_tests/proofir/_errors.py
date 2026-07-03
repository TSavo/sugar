from __future__ import annotations

from typing import NoReturn

from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)


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
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="proofir-construction-law",
            status="proofir-gap",
            observed=observed,
            blame="proofir-construction-law",
            selected=None,
            candidates=[requested],
            message=info.message,
        ),
    )
