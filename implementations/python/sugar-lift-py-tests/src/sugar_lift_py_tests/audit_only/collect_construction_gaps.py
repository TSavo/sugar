from __future__ import annotations

import re
from typing import Callable, Iterable, TypeAlias, TypeVar

from sugar_lift_py_tests.gap.info import GapKind
from sugar_lift_py_tests.gap.panic import FactoryPanic

from .audit_only_gap import AuditOnlyGap

AuditWalker: TypeAlias = tuple[str, Callable[[], object]]
T = TypeVar("T")
_FIELD = re.compile(
    r"(owner|blame|observed|requested|fix)=([^=]+?)(?=\s(?:owner|blame|observed|requested|fix)=|$)"
)
_EXPECTED_GOT = re.compile(
    r"expected (?P<requested>[A-Za-z_][A-Za-z0-9_]*) got (?P<observed>[A-Za-z_][A-Za-z0-9_]*)"
)
_EXPECTED = re.compile(r"expected (?P<requested>.+)$")
_BACKTICK = re.compile(r"`([^`]+)`")


def collect_construction_gaps(walkers: Iterable[AuditWalker]) -> list[AuditOnlyGap]:
    """Run each walker; hold FactoryPanic (the audit door) and loud TypeError
    construction gaps; re-raise everything else. Walkers continue after a gap
    so the frontier enumerates every offender, not just the first."""
    gaps: list[AuditOnlyGap] = []
    for label, walker in walkers:
        try:
            walker()
        except FactoryPanic as panic:
            # The ONE place FactoryPanic may be held -- audit enumeration.
            gaps.append(gap_from_factory_panic(label, panic))
        except TypeError as exc:
            gap = _gap_from_loud_type_error(label, str(exc))
            if gap is None:
                raise
            gaps.append(gap)
    return gaps


def collect_factory_panic(
    label: str,
    walker: Callable[[], T],
) -> tuple[T | None, AuditOnlyGap | None]:
    """Run one per-file audit walker through the sole FactoryPanic membrane.

    A successful value and a loud panic row are disjoint. Other exceptions
    propagate to the caller for their own terminal classification.
    """
    try:
        return walker(), None
    except FactoryPanic as panic:
        return None, gap_from_factory_panic(label, panic)


def gap_from_factory_panic(label: str, panic: FactoryPanic) -> AuditOnlyGap:
    """Carry the panic's own construction testimony across the audit membrane."""
    info = panic.info.to_json()
    return AuditOnlyGap(
        label=label,
        info=info,
        message=panic.info.message,
    )


def _gap_from_loud_type_error(label: str, message: str) -> AuditOnlyGap | None:
    gap_kind = _loud_gap_kind(message)
    if gap_kind is None:
        return None
    info = _info_from_loud_message(label, message, gap_kind=gap_kind)
    return AuditOnlyGap(
        label=label,
        info=info,
        message=message,
    )


def _loud_gap_kind(message: str) -> GapKind | None:
    if message.startswith("write more Floor for "):
        return GapKind.FLOOR
    if message.startswith("write more Sugar for "):
        return GapKind.SUGAR
    return None


def _info_from_loud_message(
    label: str, message: str, *, gap_kind: GapKind
) -> dict[str, str]:
    fields = {key: value.strip() for key, value in _FIELD.findall(message)}
    if fields:
        return {
            "owner": fields.get("owner", "unknown"),
            "blame": fields.get("blame", label),
            "observed": fields.get("observed", "unknown"),
            "requested": fields.get("requested", "unknown"),
            "fix": fields.get("fix", _default_fix(gap_kind)),
        }

    rest = message.split(" for ", 1)[1]
    if rest.startswith("this AST:"):
        rest = rest.removeprefix("this AST:").strip()
    elif rest.startswith("this Construction:"):
        rest = rest.removeprefix("this Construction:").strip()
    elif rest.startswith("this construction:"):
        rest = rest.removeprefix("this construction:").strip()
    owner, detail = _split_owner_detail(rest)
    requested = "unknown"
    observed = "unknown"

    if match := _EXPECTED_GOT.search(detail):
        requested = match.group("requested")
        observed = match.group("observed")
    elif match := _EXPECTED.search(detail):
        requested = match.group("requested").strip()

    if observed == "unknown":
        if match := _BACKTICK.search(owner):
            observed = match.group(1)
        elif match := _BACKTICK.search(detail):
            observed = match.group(1)
    if requested == "unknown" and "cannot project to a term" in detail:
        requested = "term"

    owner = _BACKTICK.sub("", owner).strip() or "unknown"
    return {
        "owner": owner,
        "blame": label,
        "observed": observed,
        "requested": requested,
        "fix": _default_fix(gap_kind),
    }


def _split_owner_detail(rest: str) -> tuple[str, str]:
    if ":" not in rest:
        return rest.strip(), ""
    owner, detail = rest.split(":", 1)
    return owner.strip(), detail.strip()


def _default_fix(gap_kind: GapKind) -> str:
    if gap_kind is GapKind.FLOOR:
        return "write the missing floor"
    if gap_kind is GapKind.SUGAR:
        return "write the missing sugar"
    raise TypeError(f"unhandled audit-only GapKind arm: {type(gap_kind).__name__}")
