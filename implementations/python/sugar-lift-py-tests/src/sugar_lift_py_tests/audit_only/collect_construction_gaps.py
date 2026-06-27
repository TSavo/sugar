from __future__ import annotations

from typing import Callable, Iterable, TypeAlias

from sugar_lift_py_tests.factory import FactoryGap

from .audit_only_gap import AuditOnlyGap


AuditWalker: TypeAlias = tuple[str, Callable[[], object]]


def collect_construction_gaps(walkers: Iterable[AuditWalker]) -> list[AuditOnlyGap]:
    gaps: list[AuditOnlyGap] = []
    for label, walker in walkers:
        try:
            walker()
        except FactoryGap as exc:
            gaps.append(
                AuditOnlyGap(
                    label=label,
                    info=exc.info,
                    audit_row=exc.audit_row,
                    message=str(exc),
                )
            )
    return gaps
