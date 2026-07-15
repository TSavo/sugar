from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict
from typing import Never, NoReturn

from .factory_audit_row import FactoryAuditStatus


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
class FactoryGapInfo:
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    gap_kind: GapKind = GapKind.SUGAR
    gap_locus: GapLocus = GapLocus.AST

    def __post_init__(self) -> None:
        if not isinstance(self.gap_kind, GapKind):
            raise TypeError(
                "FactoryGapInfo.gap_kind must be GapKind: owner=FactoryGapInfo "
                f"shape={type(self.gap_kind).__name__} replacement=GapKind.FLOOR"
            )
        if not isinstance(self.gap_locus, GapLocus):
            raise TypeError(
                "FactoryGapInfo.gap_locus must be GapLocus: owner=FactoryGapInfo "
                f"shape={type(self.gap_locus).__name__} "
                "replacement=GapLocus.CONSTRUCTION"
            )

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


def gap_kind_status(kind: GapKind) -> FactoryAuditStatus:
    if kind is GapKind.FLOOR:
        return FactoryAuditStatus.FLOOR_GAP
    if kind is GapKind.SUGAR:
        return FactoryAuditStatus.SUGAR_GAP
    if kind is GapKind.CONSTRUCTOR:
        return FactoryAuditStatus.CONSTRUCTOR_GAP
    if kind is GapKind.SUGAR_ORDERING:
        return FactoryAuditStatus.SUGAR_AMBIGUOUS
    if kind is GapKind.OPERATION:
        return FactoryAuditStatus.OPERATION_GAP
    if kind is GapKind.PROOFIR:
        return FactoryAuditStatus.PROOFIR_GAP
    return _unhandled_gap_kind(kind)


def _unhandled_gap_kind(kind: Never) -> NoReturn:
    raise TypeError(f"unhandled GapKind arm: {type(kind).__name__}")


def _unhandled_gap_locus(locus: Never) -> NoReturn:
    raise TypeError(f"unhandled GapLocus arm: {type(locus).__name__}")
