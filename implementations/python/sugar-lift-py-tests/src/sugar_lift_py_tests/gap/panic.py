from __future__ import annotations

from typing import NoReturn

from .info import ConstructionGap, GapKind, GapLocus


class ConstructionPanic(BaseException):
    """Kit-domain construction None arm: match(Sugar) { Some => …, None => panic!() }.

    A BaseException, NOT an Exception: ordinary ``except Exception:`` will not
    catch it, so it propagates and halts loud. The production lift child admits
    it as a sanctioned typed gap (alongside tree ``SugarNotWritten``).

    Carries only ``ConstructionGap`` testimony. Unwritten code panics until written.
    """

    def __init__(self, info: ConstructionGap) -> None:
        self.info = info
        super().__init__(
            "CONSTRUCTION PANIC: match(Sugar) { Some => cite_or_effect, None => panic!() }\n"
            f"{info.message}"
        )


def construction_panic(info: ConstructionGap) -> NoReturn:
    """Raise the construction None arm. No Incomplete soft arm; no audit row."""
    raise ConstructionPanic(info)


def _blame_prose(blame: object) -> str:
    """Project a locus to prose at the gap boundary only."""
    filename = getattr(blame, "filename", None)
    line = getattr(blame, "line", None)
    col = getattr(blame, "col", None)
    if isinstance(filename, str) and isinstance(line, int) and isinstance(col, int):
        return f"{filename}:{line}:{col}"
    return str(blame)


def construction_panic_gap(
    *,
    owner: str,
    blame: object,
    observed: str,
    requested: str,
    fix: str,
    gap_kind: GapKind = GapKind.FLOOR,
    gap_locus: GapLocus = GapLocus.CONSTRUCTION,
    **_ignored,
) -> NoReturn:
    """Mouth for residual floor/temporal None arms. Construct or panic."""
    prose = _blame_prose(blame)
    info = ConstructionGap(
        owner=owner,
        blame=prose,
        observed=observed if isinstance(observed, str) else repr(observed),
        requested=requested,
        fix=fix,
        gap_kind=gap_kind,
        gap_locus=gap_locus,
    )
    construction_panic(info)


def dig_boundary_panic(
    *,
    callee: str,
    blame: str,
    caught: str,
    reason: str,
) -> NoReturn:
    """A dig gap is not a soft ledger row. It panics like any other None arm."""
    info = ConstructionGap(
        owner="dig",
        blame=blame,
        observed=callee,
        requested="dig",
        fix=f"caught={caught} reason={reason}",
    )
    raise ConstructionPanic(info)
