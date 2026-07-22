from __future__ import annotations

from typing import NoReturn

from .audit_row import FactoryAuditRow, FactoryAuditStatus
from .info import FactoryGapInfo, GapKind, GapLocus


class FactoryPanic(BaseException):
    """The None arm of match(Sugar) { Some => cite_or_effect, None => panic!() }.

    A BaseException, NOT an Exception: a normal `except Exception:` -- the usual swallow
    -- will not catch it, so it propagates and halts loud, the way a process exit did.
    Only an audit harness that explicitly does `except FactoryPanic:` can hold it, to
    enumerate every gap instead of dying on the first. It carries the gap so the audit
    can name what to write."""

    def __init__(
        self,
        info: FactoryGapInfo,
        audit_row: FactoryAuditRow | None = None,
    ) -> None:
        self.info = info
        self.audit_row = audit_row
        super().__init__(
            "FACTORY PANIC: match(Sugar) { Some => cite_or_effect, None => panic!() }\n"
            f"{info.message}"
        )


def factory_panic(
    info: FactoryGapInfo,
    audit_row: FactoryAuditRow | None = None,
) -> NoReturn:
    """The None / no-recognizer arm. No recognizer is not a third state: there is no
    FactoryGap type and no catchable Incomplete arm. The None slot panics -- loudly,
    uncatchable by ordinary handlers -- via a BaseException that only audit mode holds.
    """
    raise FactoryPanic(info, audit_row)


def _blame_prose(blame: object) -> str:
    """Project a locus to prose at the gap boundary only.

    One SourceFragment (sugar_source_tree) answers filename/line/col via
    RuntimeEffectSite. Anything else stringifies.
    """
    filename = getattr(blame, "filename", None)
    line = getattr(blame, "line", None)
    col = getattr(blame, "col", None)
    if isinstance(filename, str) and isinstance(line, int) and isinstance(col, int):
        return f"{filename}:{line}:{col}"
    return str(blame)


def factory_panic_gap(
    *,
    owner: str,
    blame: object,
    observed: str,
    requested: str,
    fix: str,
    gap_kind: GapKind = GapKind.FLOOR,
    gap_locus: GapLocus = GapLocus.CONSTRUCTION,
    status: FactoryAuditStatus = FactoryAuditStatus.SUGAR_GAP,
    selected: str | None = None,
) -> NoReturn:
    """Mouth for residual floor/temporal None arms.

    ``blame`` may be the one tree SourceFragment (RuntimeEffectSite) or prose.
    FactoryGapInfo.blame is prose: project at this boundary, nowhere earlier.
    """
    prose = _blame_prose(blame)
    info = FactoryGapInfo(
        owner=owner,
        blame=prose,
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
        blame=prose,
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
    """A dig gap is not a soft ledger row. It panics like any other None arm."""
    info = FactoryGapInfo(
        owner="dig",
        blame=blame,
        observed=callee,
        requested="dig",
        fix=f"caught={caught} reason={reason}",
    )
    raise FactoryPanic(info)
