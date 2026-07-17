"""Closed recovered-construction-audit wire DTOs (#4264).

Two shapes share this module:

* **Leaf** (`RecoveredAuditDto`) — Python producer → Rust fold. Status is
  ``clean`` | ``failed``. No census, no fold-owned ``demandedBody`` /
  ``ownerIdentity``.
* **Tree** (`RecoveredFrontierAuditDto`) — Rust fold → CLI/wall consumers.
  Status is ``valid-empty`` | ``complete`` | ``failed``. Census and
  fold-owned identity fields are required.

Both ``from_rpc`` paths reject unknown fields so a writer change the other
language cannot parse fails in the PR, not on the next wall run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{label} unknown field(s): {', '.join(unknown)}")


def _require_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


_LEAF_AUDIT_FIELDS = frozenset(
    {
        "kind",
        "recoveryOverride",
        "status",
        "panics",
        "effects",
        "suppressedDescendants",
    }
)
_LEAF_PANIC_FIELDS = frozenset(
    {
        "kind",
        "status",
        "reason",
        "locus",
        "demandedSource",
        "terminalGapLocus",
        "gap",
    }
)
_LEAF_EFFECT_FIELDS = frozenset({"locus", "effect", "category", "status", "reason"})
_LEAF_SUPPRESSED_FIELDS = frozenset({"locus", "reason"})

_TREE_AUDIT_FIELDS = _LEAF_AUDIT_FIELDS | frozenset({"census"})
_TREE_CENSUS_FIELDS = frozenset(
    {
        "kind",
        "sourceFilesEnumerated",
        "sourceBodiesDemanded",
        "auditLeavesCompleted",
    }
)
_TREE_PANIC_FIELDS = _LEAF_PANIC_FIELDS | frozenset({"demandedBody", "ownerIdentity"})
_TREE_EFFECT_FIELDS = _LEAF_EFFECT_FIELDS | frozenset({"demandedBody"})
_TREE_SUPPRESSED_FIELDS = _LEAF_SUPPRESSED_FIELDS | frozenset({"demandedBody"})
_TREE_OWNER_FIELDS = frozenset(
    {"demandedBody", "demandedSource", "terminalGapLocus"}
)


@dataclass(frozen=True)
class RecoveredFactoryPanicDto:
    locus: str
    demanded_source: str
    terminal_gap_locus: str
    reason: str
    gap: dict[str, Any]

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

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredFactoryPanicDto:
        row = _require_mapping(data, "recovered panic")
        _reject_unknown(row, set(_LEAF_PANIC_FIELDS), "recovered panic")
        if row.get("kind") != "FactoryPanic" or row.get("status") != "mandatory-panic":
            raise ValueError("recovered panic must be a mandatory FactoryPanic")
        gap = _require_mapping(row.get("gap"), "recovered panic gap")
        return cls(
            locus=_require_str(row.get("locus"), "recovered panic locus"),
            demanded_source=_require_str(
                row.get("demandedSource"), "recovered panic demandedSource"
            ),
            terminal_gap_locus=_require_str(
                row.get("terminalGapLocus"), "recovered panic terminalGapLocus"
            ),
            reason=_require_str(row.get("reason"), "recovered panic reason"),
            gap=dict(gap),
        )


@dataclass(frozen=True)
class SuppressedAuditLocusDto:
    locus: str
    reason: str = "ancestor FactoryPanic poisoned this source locus"

    def to_rpc(self) -> dict[str, str]:
        return {"locus": self.locus, "reason": self.reason}

    @classmethod
    def from_rpc(cls, data: object) -> SuppressedAuditLocusDto:
        row = _require_mapping(data, "suppressed descendant")
        _reject_unknown(row, set(_LEAF_SUPPRESSED_FIELDS), "suppressed descendant")
        return cls(
            locus=_require_str(row.get("locus"), "suppressed descendant locus"),
            reason=_require_str(row.get("reason"), "suppressed descendant reason"),
        )


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

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredEffectDto:
        row = _require_mapping(data, "recovered effect")
        _reject_unknown(row, set(_LEAF_EFFECT_FIELDS), "recovered effect")
        return cls(
            locus=_require_str(row.get("locus"), "recovered effect locus"),
            effect=_require_str(row.get("effect"), "recovered effect effect"),
            category=_require_str(row.get("category"), "recovered effect category"),
            status=_require_str(row.get("status"), "recovered effect status"),
            reason=_require_str(row.get("reason"), "recovered effect reason"),
        )


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

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredAuditDto:
        row = _require_mapping(data, "recovered audit leaf")
        _reject_unknown(row, set(_LEAF_AUDIT_FIELDS), "recovered audit leaf")
        if row.get("kind") != "recovered-construction-audit":
            raise ValueError("recovered audit leaf has the wrong kind")
        if row.get("recoveryOverride") is not True:
            raise ValueError("recovered audit leaf lacks recoveryOverride")
        panics = [
            RecoveredFactoryPanicDto.from_rpc(item)
            for item in _require_list(row.get("panics"), "recovered audit leaf panics")
        ]
        effects = [
            RecoveredEffectDto.from_rpc(item)
            for item in _require_list(row.get("effects"), "recovered audit leaf effects")
        ]
        suppressed = [
            SuppressedAuditLocusDto.from_rpc(item)
            for item in _require_list(
                row.get("suppressedDescendants"),
                "recovered audit leaf suppressedDescendants",
            )
        ]
        expected_status = "failed" if panics else "clean"
        if row.get("status") != expected_status:
            raise ValueError(
                f"recovered audit leaf status must be {expected_status!r} "
                f"for panics={len(panics)}"
            )
        return cls(
            panics=panics,
            effects=effects,
            suppressed_descendants=suppressed,
        )


@dataclass(frozen=True)
class RecoveredFrontierCensusDto:
    source_files_enumerated: int
    source_bodies_demanded: int
    audit_leaves_completed: int

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "recovered-frontier-census",
            "sourceFilesEnumerated": self.source_files_enumerated,
            "sourceBodiesDemanded": self.source_bodies_demanded,
            "auditLeavesCompleted": self.audit_leaves_completed,
        }

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredFrontierCensusDto:
        row = _require_mapping(data, "recovered frontier census")
        _reject_unknown(row, set(_TREE_CENSUS_FIELDS), "recovered frontier census")
        if row.get("kind") != "recovered-frontier-census":
            raise ValueError("census receipt has the wrong kind")
        return cls(
            source_files_enumerated=_require_int(
                row.get("sourceFilesEnumerated"), "sourceFilesEnumerated"
            ),
            source_bodies_demanded=_require_int(
                row.get("sourceBodiesDemanded"), "sourceBodiesDemanded"
            ),
            audit_leaves_completed=_require_int(
                row.get("auditLeavesCompleted"), "auditLeavesCompleted"
            ),
        )


@dataclass(frozen=True)
class RecoveredPanicOwnerIdentityDto:
    demanded_body: dict[str, Any]
    demanded_source: str
    terminal_gap_locus: str

    def to_rpc(self) -> dict[str, Any]:
        return {
            "demandedBody": dict(self.demanded_body),
            "demandedSource": self.demanded_source,
            "terminalGapLocus": self.terminal_gap_locus,
        }

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredPanicOwnerIdentityDto:
        row = _require_mapping(data, "recovered panic ownerIdentity")
        _reject_unknown(row, set(_TREE_OWNER_FIELDS), "recovered panic ownerIdentity")
        body = _require_mapping(row.get("demandedBody"), "ownerIdentity.demandedBody")
        return cls(
            demanded_body=dict(body),
            demanded_source=_require_str(
                row.get("demandedSource"), "ownerIdentity.demandedSource"
            ),
            terminal_gap_locus=_require_str(
                row.get("terminalGapLocus"), "ownerIdentity.terminalGapLocus"
            ),
        )


@dataclass(frozen=True)
class RecoveredFactoryPanicTreeDto:
    locus: str
    demanded_source: str
    terminal_gap_locus: str
    reason: str
    gap: dict[str, Any]
    demanded_body: dict[str, Any]
    owner_identity: RecoveredPanicOwnerIdentityDto

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "FactoryPanic",
            "status": "mandatory-panic",
            "reason": self.reason,
            "locus": self.locus,
            "gap": dict(self.gap),
            "demandedSource": self.demanded_source,
            "terminalGapLocus": self.terminal_gap_locus,
            "demandedBody": dict(self.demanded_body),
            "ownerIdentity": self.owner_identity.to_rpc(),
        }

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredFactoryPanicTreeDto:
        row = _require_mapping(data, "recovered tree panic")
        _reject_unknown(row, set(_TREE_PANIC_FIELDS), "recovered tree panic")
        if row.get("kind") != "FactoryPanic" or row.get("status") != "mandatory-panic":
            raise ValueError("recovered tree panic must be a mandatory FactoryPanic")
        gap = _require_mapping(row.get("gap"), "recovered tree panic gap")
        body = _require_mapping(row.get("demandedBody"), "recovered tree panic demandedBody")
        owner = RecoveredPanicOwnerIdentityDto.from_rpc(row.get("ownerIdentity"))
        demanded_source = _require_str(
            row.get("demandedSource"), "recovered tree panic demandedSource"
        )
        terminal_gap_locus = _require_str(
            row.get("terminalGapLocus"), "recovered tree panic terminalGapLocus"
        )
        expected = RecoveredPanicOwnerIdentityDto(
            demanded_body=dict(body),
            demanded_source=demanded_source,
            terminal_gap_locus=terminal_gap_locus,
        )
        if owner != expected:
            raise ValueError("recovered tree panic ownerIdentity does not match ownership")
        return cls(
            locus=_require_str(row.get("locus"), "recovered tree panic locus"),
            demanded_source=demanded_source,
            terminal_gap_locus=terminal_gap_locus,
            reason=_require_str(row.get("reason"), "recovered tree panic reason"),
            gap=dict(gap),
            demanded_body=dict(body),
            owner_identity=owner,
        )


@dataclass(frozen=True)
class RecoveredEffectTreeDto:
    locus: str
    effect: str
    category: str
    status: str
    reason: str
    demanded_body: dict[str, Any]

    def to_rpc(self) -> dict[str, Any]:
        return {
            "locus": self.locus,
            "effect": self.effect,
            "category": self.category,
            "status": self.status,
            "reason": self.reason,
            "demandedBody": dict(self.demanded_body),
        }

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredEffectTreeDto:
        row = _require_mapping(data, "recovered tree effect")
        _reject_unknown(row, set(_TREE_EFFECT_FIELDS), "recovered tree effect")
        body = _require_mapping(row.get("demandedBody"), "recovered tree effect demandedBody")
        return cls(
            locus=_require_str(row.get("locus"), "recovered tree effect locus"),
            effect=_require_str(row.get("effect"), "recovered tree effect effect"),
            category=_require_str(row.get("category"), "recovered tree effect category"),
            status=_require_str(row.get("status"), "recovered tree effect status"),
            reason=_require_str(row.get("reason"), "recovered tree effect reason"),
            demanded_body=dict(body),
        )


@dataclass(frozen=True)
class SuppressedAuditLocusTreeDto:
    locus: str
    reason: str
    demanded_body: dict[str, Any]

    def to_rpc(self) -> dict[str, Any]:
        return {
            "locus": self.locus,
            "reason": self.reason,
            "demandedBody": dict(self.demanded_body),
        }

    @classmethod
    def from_rpc(cls, data: object) -> SuppressedAuditLocusTreeDto:
        row = _require_mapping(data, "recovered tree suppressed descendant")
        _reject_unknown(
            row, set(_TREE_SUPPRESSED_FIELDS), "recovered tree suppressed descendant"
        )
        body = _require_mapping(
            row.get("demandedBody"), "recovered tree suppressed demandedBody"
        )
        return cls(
            locus=_require_str(row.get("locus"), "recovered tree suppressed locus"),
            reason=_require_str(row.get("reason"), "recovered tree suppressed reason"),
            demanded_body=dict(body),
        )


@dataclass(frozen=True)
class RecoveredFrontierAuditDto:
    """Closed tree-level recovered-construction-audit (fold output)."""

    status: str
    census: RecoveredFrontierCensusDto
    panics: list[RecoveredFactoryPanicTreeDto] = field(default_factory=list)
    effects: list[RecoveredEffectTreeDto] = field(default_factory=list)
    suppressed_descendants: list[SuppressedAuditLocusTreeDto] = field(
        default_factory=list
    )

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "recovered-construction-audit",
            "recoveryOverride": True,
            "status": self.status,
            "census": self.census.to_rpc(),
            "panics": [panic.to_rpc() for panic in self.panics],
            "effects": [effect.to_rpc() for effect in self.effects],
            "suppressedDescendants": [
                locus.to_rpc() for locus in self.suppressed_descendants
            ],
        }

    @classmethod
    def from_rpc(cls, data: object) -> RecoveredFrontierAuditDto:
        row = _require_mapping(data, "recovered audit tree")
        _reject_unknown(row, set(_TREE_AUDIT_FIELDS), "recovered audit tree")
        if row.get("kind") != "recovered-construction-audit":
            raise ValueError("recovered audit tree has the wrong kind")
        if row.get("recoveryOverride") is not True:
            raise ValueError("recovered audit tree lacks recoveryOverride")
        census = RecoveredFrontierCensusDto.from_rpc(row.get("census"))
        if census.source_files_enumerated != census.source_bodies_demanded:
            raise ValueError(
                "source body census mismatch: "
                f"enumerated={census.source_files_enumerated} "
                f"demanded={census.source_bodies_demanded}"
            )
        panics = [
            RecoveredFactoryPanicTreeDto.from_rpc(item)
            for item in _require_list(row.get("panics"), "recovered audit tree panics")
        ]
        effects = [
            RecoveredEffectTreeDto.from_rpc(item)
            for item in _require_list(row.get("effects"), "recovered audit tree effects")
        ]
        suppressed = [
            SuppressedAuditLocusTreeDto.from_rpc(item)
            for item in _require_list(
                row.get("suppressedDescendants"),
                "recovered audit tree suppressedDescendants",
            )
        ]
        status = _require_str(row.get("status"), "recovered audit tree status")
        if status == "valid-empty":
            if (
                census.source_files_enumerated != 0
                or census.audit_leaves_completed != 0
                or panics
            ):
                raise ValueError("valid-empty frontier requires a zero source census")
        elif status == "complete":
            if census.source_files_enumerated == 0 or panics:
                raise ValueError("complete frontier requires sources and zero panics")
        elif status == "failed":
            if not panics:
                raise ValueError("failed frontier requires panics")
        else:
            raise ValueError(f"recovered audit tree has illegal status={status!r}")
        return cls(
            status=status,
            census=census,
            panics=panics,
            effects=effects,
            suppressed_descendants=suppressed,
        )
