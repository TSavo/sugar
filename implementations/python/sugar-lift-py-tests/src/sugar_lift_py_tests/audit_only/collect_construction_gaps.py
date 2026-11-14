from __future__ import annotations

from typing import Callable, Iterable, TypeAlias, TypeVar

from sugar_lift_py_tests.gap.panic import ConstructionPanic

from .audit_only_gap import AuditOnlyGap

AuditWalker: TypeAlias = tuple[str, Callable[[], object]]
T = TypeVar("T")


def collect_construction_gaps(walkers: Iterable[AuditWalker]) -> list[AuditOnlyGap]:
    """Run each walker; hold ConstructionPanic (the audit door); re-raise
    everything else. Walkers continue after a gap so the frontier enumerates
    every offender, not just the first."""
    gaps: list[AuditOnlyGap] = []
    for label, walker in walkers:
        try:
            walker()
        except ConstructionPanic as panic:
            # The ONE place ConstructionPanic may be held -- audit enumeration.
            gaps.append(gap_from_construction_panic(label, panic))
    return gaps


def collect_construction_panic(
    label: str,
    walker: Callable[[], T],
) -> tuple[T | None, AuditOnlyGap | None]:
    """Run one per-file audit walker through the sole ConstructionPanic membrane.

    A successful value and a loud panic row are disjoint. Other exceptions
    propagate to the caller for their own terminal classification.
    """
    try:
        return walker(), None
    except ConstructionPanic as panic:
        return None, gap_from_construction_panic(label, panic)


def gap_from_construction_panic(label: str, panic: ConstructionPanic) -> AuditOnlyGap:
    """Carry the panic's own construction testimony across the audit membrane."""
    info = panic.info.to_json()
    return AuditOnlyGap(
        label=label,
        info=info,
        message=panic.info.message,
    )
