"""Construction gap testimony — independent of audit projection.

``ConstructionGap`` / ``GapKind`` / ``GapLocus`` are the pure gap authority.
Audit status projection (``gap_kind_status`` → ``ConstructionAuditStatus``)
lives on the audit-row boundary, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Dict
from typing import Never, NoReturn

if TYPE_CHECKING:
    from sugar_lift_py_tests.sealed_ground import RefusalDecidability

# ``owner`` is the panic board's DISPATCH KEY: every row is worked as
# (owner × value category), so an owner that is not a name makes the row
# undispatchable. Two shapes are not names and are rejected at construction:
#
# ``<SourceFragment 'x.py' [12, 34) node=Call>``
#     an object projection. ``SourceFragment`` defines no ``__str__``, so
#     ``str(fragment)`` silently yields its ``__repr__``; a call site that
#     passed ``owner=str(self.site)`` minted a row whose owner named an
#     address, not a law.
# ``pandas/core/frame.py:1234:8``
#     a source coordinate. That is ``blame``'s currency, not ``owner``'s.
#     Threading it through ``owner`` gives every occurrence of one law a
#     distinct owner, which scatters a single gap across the whole board.
#
# A name may contain spaces (``collection ListValue``) and dots
# (``StringValue.contains``) — those are real owners on the board, so the
# tooth names the two malformed shapes rather than whitelisting a spelling.
_OBJECT_PROJECTION = re.compile(r"^<.*>$", re.S)
_SOURCE_COORDINATE = re.compile(r":\d+:\d+$")


def _reject_non_name_owner(owner: object) -> None:
    """The owner tooth: a gap that cannot name its owner cannot be worked."""
    if not isinstance(owner, str) or not owner:
        raise TypeError(
            "ConstructionGap.owner must be a non-empty name: "
            f"owner=ConstructionGap shape={type(owner).__name__} "
            "replacement=name the law that has no arm"
        )
    if _OBJECT_PROJECTION.match(owner):
        raise TypeError(
            "ConstructionGap.owner must be a name, not an object projection: "
            f"owner=ConstructionGap observed={owner!r} "
            "replacement=pass the owning law's own name (type(self).__name__ "
            "or the method name); carry the fragment in blame"
        )
    if _SOURCE_COORDINATE.search(owner):
        raise TypeError(
            "ConstructionGap.owner must be a name, not a source coordinate: "
            f"owner=ConstructionGap observed={owner!r} "
            "replacement=pass the owning law's own name; a file:line:col "
            "coordinate is blame's currency, never owner's"
        )


class GapKind(str, Enum):
    FLOOR = "Floor"
    SUGAR = "Sugar"
    CONSTRUCTOR = "Constructor"
    SUGAR_ORDERING = "Sugar ordering"
    OPERATION = "Operation"
    PROOFIR = "ProofIR"


class GapLocus(str, Enum):
    AST = "AST"
    CONSTRUCTION = "Construction"
    PROJECTION = "Projection"
    REDUCE = "Reduce"
    METHOD_NAME = "method_name"
    VOCABULARY = "Vocabulary"
    EMISSION = "Emission"
    CONSTRUCTION_LAW = "ConstructionLaw"


@dataclass(frozen=True)
class ConstructionGap:
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    gap_kind: GapKind = GapKind.SUGAR
    gap_locus: GapLocus = GapLocus.AST
    # Recognition outcome already computed for this gap's callee, when the
    # producer has one (#5252/#5913 audit — recognize_callee_universe threw
    # this away once it decided pass/fail). Empty string when the producer
    # does not (yet) compute a callee resolution — never invented downstream.
    resolution_kind: str = ""
    # Sealed RefusalDecidability (Criterion 3). Default kit-incomplete when
    # omitted so legacy ConstructionGap(...) mints still carry a closed ground.
    decidability: "RefusalDecidability | None" = None

    def __post_init__(self) -> None:
        if self.decidability is None:
            from sugar_lift_py_tests.sealed_ground import kit_incomplete

            object.__setattr__(
                self,
                "decidability",
                kit_incomplete(owner=self.owner, observed=self.observed),
            )
        else:
            from sugar_lift_py_tests.sealed_ground import (
                KitConstructionIncomplete,
                is_refusal_decidability,
                require_refusal_ground_holds,
            )

            if not is_refusal_decidability(self.decidability):
                raise TypeError(
                    "ConstructionGap.decidability must be RefusalDecidability: "
                    f"shape={type(self.decidability).__name__}"
                )
            # Kit-incomplete always holds. Runtime grounds need world — checked
            # only at construction_panic_gap(..., world=), not at bare rebuild.
            if isinstance(self.decidability, KitConstructionIncomplete):
                require_refusal_ground_holds(self.decidability, world=None)
        if not isinstance(self.gap_kind, GapKind):
            raise TypeError(
                "ConstructionGap.gap_kind must be GapKind: owner=ConstructionGap "
                f"shape={type(self.gap_kind).__name__} replacement=GapKind.FLOOR"
            )
        if not isinstance(self.gap_locus, GapLocus):
            raise TypeError(
                "ConstructionGap.gap_locus must be GapLocus: owner=ConstructionGap "
                f"shape={type(self.gap_locus).__name__} "
                "replacement=GapLocus.CONSTRUCTION"
            )
        _reject_non_name_owner(self.owner)

    @property
    def message(self) -> str:
        return (
            f"write more {gap_kind_label(self.gap_kind)} for this "
            f"{gap_locus_label(self.gap_locus)}: "
            f"owner={self.owner} blame={self.blame} observed={self.observed} "
            f"requested={self.requested} fix={self.fix}"
        )

    def to_json(self) -> Dict[str, str]:
        return {
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
            "resolution_kind": self.resolution_kind,
            "gap_kind": gap_kind_label(self.gap_kind),
            "gap_locus": gap_locus_label(self.gap_locus),
        }


def gap_kind_label(kind: GapKind) -> str:
    if kind is GapKind.FLOOR:
        return kind.value
    if kind is GapKind.SUGAR:
        return kind.value
    if kind is GapKind.CONSTRUCTOR:
        return kind.value
    if kind is GapKind.SUGAR_ORDERING:
        return kind.value
    if kind is GapKind.OPERATION:
        return kind.value
    if kind is GapKind.PROOFIR:
        return kind.value
    return _unhandled_gap_kind(kind)


def gap_locus_label(locus: GapLocus) -> str:
    if locus is GapLocus.AST:
        return locus.value
    if locus is GapLocus.CONSTRUCTION:
        return locus.value
    if locus is GapLocus.PROJECTION:
        return locus.value
    if locus is GapLocus.REDUCE:
        return locus.value
    if locus is GapLocus.METHOD_NAME:
        return locus.value
    if locus is GapLocus.VOCABULARY:
        return locus.value
    if locus is GapLocus.EMISSION:
        return locus.value
    if locus is GapLocus.CONSTRUCTION_LAW:
        return locus.value
    return _unhandled_gap_locus(locus)


def _unhandled_gap_kind(kind: Never) -> NoReturn:
    raise TypeError(f"unhandled GapKind arm: {type(kind).__name__}")


def _unhandled_gap_locus(locus: Never) -> NoReturn:
    raise TypeError(f"unhandled GapLocus arm: {type(locus).__name__}")
