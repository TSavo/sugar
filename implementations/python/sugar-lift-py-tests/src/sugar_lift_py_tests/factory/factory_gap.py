from __future__ import annotations

import os
import sys
from typing import NoReturn

from .factory_audit_row import FactoryAuditRow
from .factory_gap_info import FactoryGapInfo, GapKind, GapLocus

# Terminal exit for the None / no-recognizer arm of
# match(Sugar) { Some => cite_or_effect, None => panic!() }.
# Non-zero, process-fatal, not catchable as a value to continue on.
_FACTORY_PANIC_EXIT_CODE = 1


def factory_panic(
    info: FactoryGapInfo,
    audit_row: FactoryAuditRow | None = None,
) -> NoReturn:
    """Halt the process: no recognizer is not a third state.

    There is no FactoryGap type. There is no catchable Incomplete arm.
    The None slot panics.
    """
    sys.stderr.write(
        "FACTORY PANIC: match(Sugar) { Some => cite_or_effect, None => panic!() }\n"
        f"{info.message}\n"
    )
    if audit_row is not None:
        sys.stderr.write(f"audit={audit_row.to_json()}\n")
    sys.stderr.flush()
    os._exit(_FACTORY_PANIC_EXIT_CODE)


def factory_panic_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
    gap_kind: GapKind = GapKind.FLOOR,
    gap_locus: GapLocus = GapLocus.CONSTRUCTION,
    status: str = "sugar-gap",
    selected: str | None = None,
) -> NoReturn:
    """Mouth for sites that previously built FactoryGapEffect / FactoryGap."""
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=gap_kind,
        gap_locus=gap_locus,
    )
    audit_row = FactoryAuditRow(
        role=requested,
        status=status,
        observed=observed,
        blame=blame,
        selected=selected,
        candidates=[],
        message=info.message,
    )
    factory_panic(info, audit_row)


def dig_boundary_panic(
    *,
    callee: str,
    blame: str,
    caught: str,
    reason: str,
) -> NoReturn:
    """Dig refusal is not a soft ledger row. Sink."""
    sys.stderr.write(
        "DIG BOUNDARY PANIC: match(Sugar) { Some => cite_or_effect, None => panic!() }\n"
        f"callee={callee} blame={blame} caught={caught} reason={reason}\n"
    )
    sys.stderr.flush()
    os._exit(_FACTORY_PANIC_EXIT_CODE)
