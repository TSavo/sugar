"""Test-owned evidence for the SourceFile construction-door auditor.

Production must not import this module. Only
``sourcefile_construction_door_auditor`` may mint
``SourceFileConstructionDoorEvidence``; consumer tests inspect via
``assert_test_owned_evidence``.

This is **not** Law-of-One meaning evidence. It closes construction ownership,
product privacy, and zero-work projection only — see the auditor module
docstring for offender classes, structural blindness, and retirement paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceSite:
    path: Path
    line: int
    lexical_owner: tuple[str, ...]
    symbol: str


@dataclass(frozen=True)
class OwnerCallPathEvidence:
    owner: EvidenceSite
    canonical_source_file_entry: EvidenceSite
    canonical_call: EvidenceSite
    other_owner_definitions: tuple[EvidenceSite, ...]
    constructor_calls: tuple[EvidenceSite, ...]
    dynamic_calls: tuple[EvidenceSite, ...]
    forwarders: tuple[EvidenceSite, ...]
    audited_forwarders: tuple[EvidenceSite, ...]
    unauthorized_source_constructors: tuple[EvidenceSite, ...]
    adapter_overrides: tuple[EvidenceSite, ...]
    discovered_calls: int
    audited_calls: int


@dataclass(frozen=True)
class SourceFileSurfaceEvidence:
    oracle_intake: EvidenceSite
    work_entry: EvidenceSite
    intake_constructor_edges: tuple[EvidenceSite, ...]
    forbidden_intake_work_edges: tuple[EvidenceSite, ...]
    discovered_surfaces: int
    audited_surfaces: int


@dataclass(frozen=True)
class PrivacyLeakEvidence:
    product_type: type
    relation_type: type
    member_type: type
    leaf_assertion_type: type
    definitions: tuple[EvidenceSite, ...]
    constructions: tuple[EvidenceSite, ...]
    aliases: tuple[EvidenceSite, ...]
    reexports: tuple[EvidenceSite, ...]
    wrappers: tuple[EvidenceSite, ...]
    caches: tuple[EvidenceSite, ...]
    second_product_doors: tuple[EvidenceSite, ...]
    public_constructors: tuple[EvidenceSite, ...]
    serialization_doors: tuple[EvidenceSite, ...]
    discovered_references: int
    audited_references: int
    discovered_reference_sites: tuple[EvidenceSite, ...]
    audited_reference_sites: tuple[EvidenceSite, ...]
    unaudited_reference_sites: tuple[EvidenceSite, ...]
    discovered_capabilities: tuple[EvidenceSite, ...]
    audited_capabilities: tuple[EvidenceSite, ...]
    unaudited_capabilities: tuple[EvidenceSite, ...]
    producer_relation_roster: tuple[EvidenceSite, ...]
    observed_relation_roster: tuple[EvidenceSite, ...]
    unobserved_relation_roster: tuple[EvidenceSite, ...]
    discovered_closed_types: tuple[type, ...]
    audited_closed_types: tuple[type, ...]
    unaudited_closed_types: tuple[type, ...]
    product_relation_types: tuple[type, ...]
    receipt_relation_types: tuple[type, ...]
    product_only_relation_types: tuple[type, ...]
    receipt_product_backreferences: int


@dataclass(frozen=True)
class ProjectionClosureEvidence:
    definition: EvidenceSite
    callers: tuple[EvidenceSite, ...]
    dynamic_edges: tuple[EvidenceSite, ...]
    aliases: tuple[EvidenceSite, ...]
    reexports: tuple[EvidenceSite, ...]
    wrappers: tuple[EvidenceSite, ...]
    non_product_callers: tuple[EvidenceSite, ...]
    legacy_doors: tuple[EvidenceSite, ...]
    discovered_edges: int
    audited_edges: int


@dataclass(frozen=True)
class ProtocolZeroWorkEvidence:
    constructed_product: object
    closed_roll_call: object
    reporting_projection: object
    constructor_events: int
    foreign_constructor_events: int
    truthful_protocol: tuple[tuple[str, int], ...]
    foreign_protocol: tuple[tuple[str, int], ...]
    reporter_before: tuple[object, ...]
    reporter_after: tuple[object, ...]
    protocol_before: tuple[tuple[str, int], ...]
    protocol_after: tuple[tuple[str, int], ...]
    repeated_projection_results: tuple[object, ...]
    truthful_projection: object
    foreign_product: object
    foreign_projection: object


@dataclass(frozen=True, init=False)
class SourceFileConstructionDoorEvidence:
    discovered: tuple[Path, ...]
    audited: tuple[Path, ...]
    unaudited: tuple[Path, ...]
    discovery_errors: tuple[str, ...]
    duplicate_modules: tuple[tuple[str, tuple[Path, ...]], ...]
    owner_path: OwnerCallPathEvidence
    source_file_surfaces: SourceFileSurfaceEvidence
    privacy: PrivacyLeakEvidence
    projection: ProjectionClosureEvidence
    zero_work: ProtocolZeroWorkEvidence

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError(
            "SourceFileConstructionDoorEvidence is sealed; only "
            "sourcefile_construction_door_auditor may mint it"
        )

    def assert_closed(self) -> None:
        assert self.discovered, (
            "sourcefile construction-door discovered denominator must be non-empty"
        )
        assert set(self.discovered) == set(self.audited) | set(self.unaudited)
        assert set(self.audited).isdisjoint(self.unaudited)
        assert self.unaudited == ()
        assert self.discovery_errors == ()
        assert self.duplicate_modules == ()

        owner = self.owner_path
        assert owner.other_owner_definitions == ()
        assert owner.constructor_calls
        assert owner.canonical_call in owner.constructor_calls
        assert owner.dynamic_calls == ()
        assert owner.forwarders
        assert owner.forwarders == owner.audited_forwarders
        assert owner.unauthorized_source_constructors == ()
        assert owner.adapter_overrides == ()
        assert owner.discovered_calls == owner.audited_calls > 0
        assert (
            *owner.canonical_call.lexical_owner,
            owner.canonical_call.symbol,
        ) == (
            *owner.canonical_source_file_entry.lexical_owner,
            owner.canonical_source_file_entry.symbol,
        )

        surfaces = self.source_file_surfaces
        assert len(surfaces.intake_constructor_edges) == 1
        assert surfaces.forbidden_intake_work_edges == ()
        assert surfaces.discovered_surfaces == surfaces.audited_surfaces > 0
        assert surfaces.oracle_intake == owner.canonical_source_file_entry
        assert surfaces.work_entry == owner.owner

        privacy = self.privacy
        assert privacy.discovered_closed_types
        assert privacy.audited_closed_types == privacy.discovered_closed_types
        assert privacy.unaudited_closed_types == ()
        assert privacy.receipt_product_backreferences == 1
        assert privacy.product_only_relation_types
        assert set(privacy.product_only_relation_types) == {
            type(row)
            for row in self.zero_work.constructed_product.lexical_call_rows
        }
        assert set(privacy.product_relation_types) == {
            *privacy.receipt_relation_types,
            *privacy.product_only_relation_types,
        }
        assert set(privacy.discovered_closed_types) == {
            privacy.product_type,
            *privacy.product_relation_types,
        }
        assert len(privacy.definitions) == len(privacy.audited_closed_types)
        assert len(privacy.constructions) >= len(privacy.audited_closed_types)
        assert privacy.aliases == ()
        assert privacy.reexports == ()
        assert privacy.wrappers == ()
        assert privacy.caches == ()
        assert privacy.second_product_doors == ()
        assert privacy.public_constructors == ()
        assert privacy.serialization_doors == ()
        assert privacy.discovered_references == privacy.audited_references > 0
        assert privacy.discovered_reference_sites == privacy.audited_reference_sites
        assert privacy.unaudited_reference_sites == ()
        assert privacy.discovered_capabilities == privacy.audited_capabilities
        assert privacy.unaudited_capabilities == ()
        assert privacy.producer_relation_roster == privacy.observed_relation_roster
        assert privacy.unobserved_relation_roster == ()
        assert {
            privacy.product_type,
            privacy.relation_type,
            privacy.member_type,
            privacy.leaf_assertion_type,
        } <= set(privacy.discovered_closed_types)
        assert privacy.leaf_assertion_type is type(
            self.zero_work.constructed_product.leaf_assertion_rows[0]
        )
        leaf = self.zero_work.constructed_product.leaf_assertion_rows[0]
        assert leaf.construction_event_identity is (
            self.zero_work.constructed_product.construction_event_receipt
            .construction_event_identity
        )

        projection = self.projection
        assert projection.callers
        assert projection.dynamic_edges == ()
        assert projection.aliases == ()
        assert projection.reexports == ()
        assert projection.wrappers == ()
        assert projection.non_product_callers == ()
        assert projection.legacy_doors == ()
        assert projection.discovered_edges == projection.audited_edges > 0

        zero = self.zero_work
        assert zero.constructor_events == 1
        assert zero.foreign_constructor_events == 1
        assert zero.truthful_protocol
        assert zero.foreign_protocol
        assert zero.closed_roll_call is getattr(
            zero.constructed_product, "closed_roll_call"
        )
        assert zero.reporting_projection is zero.truthful_projection
        assert zero.reporter_after == zero.reporter_before
        assert zero.protocol_after == zero.protocol_before
        assert zero.repeated_projection_results
        assert all(
            result is zero.reporting_projection
            for result in zero.repeated_projection_results
        )
        assert zero.foreign_product is not zero.constructed_product
        assert zero.foreign_projection is not zero.reporting_projection
        assert zero.foreign_projection is getattr(
            zero.foreign_product, "reporting_projection"
        )


def assert_test_owned_evidence(evidence: Any) -> SourceFileConstructionDoorEvidence:
    """Reject production DTOs/lookalikes and validate the complete evidence."""
    assert type(evidence) is SourceFileConstructionDoorEvidence
    assert _MINTED_EVIDENCE_IDENTITIES.get(id(evidence)) is evidence
    evidence.assert_closed()
    return evidence


_MINTED_EVIDENCE_IDENTITIES: dict[int, SourceFileConstructionDoorEvidence] = {}


def _mint_test_owned_evidence(
    *,
    discovered: tuple[Path, ...],
    audited: tuple[Path, ...],
    unaudited: tuple[Path, ...],
    discovery_errors: tuple[str, ...],
    duplicate_modules: tuple[tuple[str, tuple[Path, ...]], ...],
    owner_path: OwnerCallPathEvidence,
    source_file_surfaces: SourceFileSurfaceEvidence,
    privacy: PrivacyLeakEvidence,
    projection: ProjectionClosureEvidence,
    zero_work: ProtocolZeroWorkEvidence,
) -> SourceFileConstructionDoorEvidence:
    """Private mint — only ``sourcefile_construction_door_auditor`` may call."""
    evidence = object.__new__(SourceFileConstructionDoorEvidence)
    for name, value in locals().items():
        if name != "evidence":
            object.__setattr__(evidence, name, value)
    _MINTED_EVIDENCE_IDENTITIES[id(evidence)] = evidence
    return evidence
