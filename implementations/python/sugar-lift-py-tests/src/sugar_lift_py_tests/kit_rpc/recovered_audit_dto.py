from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecoveredFactoryPanicDto:
    locus: str
    demanded_source: str
    terminal_gap_locus: str
    reason: str
    gap: dict[str, str]

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "FactoryPanic",
            "status": "mandatory-panic",
            "reason": self.reason,
            "locus": self.locus,
            "demandedSource": self.demanded_source,
            "terminalGapLocus": self.terminal_gap_locus,
            "gap": dict(self.gap),
        }


@dataclass(frozen=True)
class SuppressedAuditLocusDto:
    locus: str
    reason: str = "ancestor FactoryPanic poisoned this source locus"

    def to_rpc(self) -> dict[str, str]:
        return {"locus": self.locus, "reason": self.reason}


@dataclass(frozen=True)
class RecoveredEffectDto:
    locus: str
    effect: str
    category: str
    status: str
    reason: str

    def to_rpc(self) -> dict[str, str]:
        return {
            "locus": self.locus,
            "effect": self.effect,
            "category": self.category,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RecoveredAuditDto:
    """Diagnostic-only panic inventory; deliberately carries no ProofIR lanes."""

    panics: list[RecoveredFactoryPanicDto] = field(default_factory=list)
    effects: list[RecoveredEffectDto] = field(default_factory=list)
    suppressed_descendants: list[SuppressedAuditLocusDto] = field(default_factory=list)

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "recovered-construction-audit",
            "recoveryOverride": True,
            "status": "failed" if self.panics else "clean",
            "panics": [panic.to_rpc() for panic in self.panics],
            "effects": [effect.to_rpc() for effect in self.effects],
            "suppressedDescendants": [
                locus.to_rpc() for locus in self.suppressed_descendants
            ],
        }
