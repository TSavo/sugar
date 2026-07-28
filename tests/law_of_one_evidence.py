"""Test-owned evidence contract for LAW_OF_ONE.

Production must not import this module.  The independent repository auditor
constructs these values; producer and consumer tests may only inspect them.
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
    other_constructor_calls: tuple[EvidenceSite, ...]
    forwarders: tuple[EvidenceSite, ...]
    adapter_overrides: tuple[EvidenceSite, ...]
    discovered_calls: int
    audited_calls: int


@dataclass(frozen=True)
class SourceFileSurfaceEvidence:
    canonical_surface: EvidenceSite
    pure_surfaces: tuple[EvidenceSite, ...]
    constructing_secondary_surfaces: tuple[EvidenceSite, ...]
    discovered_surfaces: int
    audited_surfaces: int


@dataclass(frozen=True)
class PrivacyLeakEvidence:
    product_type: type
    relation_type: type
    member_type: type
    definitions: tuple[EvidenceSite, ...]
    constructions: tuple[EvidenceSite, ...]
    aliases: tuple[EvidenceSite, ...]
    reexports: tuple[EvidenceSite, ...]
    public_constructors: tuple[EvidenceSite, ...]
    serialization_doors: tuple[EvidenceSite, ...]
    discovered_references: int
    audited_references: int


@dataclass(frozen=True)
class ProjectionClosureEvidence:
    definition: EvidenceSite
    callers: tuple[EvidenceSite, ...]
    dynamic_edges: tuple[EvidenceSite, ...]
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
class LawOfOneEvidence:
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
            "LawOfOneEvidence is sealed; only the independent test auditor may mint it"
        )

    def assert_closed(self) -> None:
        assert self.discovered, "LAW_OF_ONE discovered denominator must be non-empty"
        assert set(self.discovered) == set(self.audited) | set(self.unaudited)
        assert set(self.audited).isdisjoint(self.unaudited)
        assert self.unaudited == ()
        assert self.discovery_errors == ()
        assert self.duplicate_modules == ()

        owner = self.owner_path
        assert owner.other_owner_definitions == ()
        assert owner.other_constructor_calls == ()
        assert owner.forwarders == ()
        assert owner.adapter_overrides == ()
        assert owner.discovered_calls == owner.audited_calls > 0
        assert owner.canonical_call.lexical_owner == (
            *owner.canonical_source_file_entry.lexical_owner,
            owner.canonical_source_file_entry.symbol,
        )

        surfaces = self.source_file_surfaces
        assert surfaces.constructing_secondary_surfaces == ()
        assert surfaces.discovered_surfaces == surfaces.audited_surfaces > 0
        assert surfaces.canonical_surface == owner.canonical_source_file_entry

        privacy = self.privacy
        assert len(privacy.definitions) == 3
        assert len(privacy.constructions) == 3
        assert privacy.aliases == ()
        assert privacy.reexports == ()
        assert privacy.public_constructors == ()
        assert privacy.serialization_doors == ()
        assert privacy.discovered_references == privacy.audited_references > 0
        assert len({privacy.product_type, privacy.relation_type, privacy.member_type}) == 3

        projection = self.projection
        assert projection.callers
        assert projection.dynamic_edges == ()
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


def assert_test_owned_evidence(evidence: Any) -> LawOfOneEvidence:
    """Reject production DTOs/lookalikes and validate the complete evidence."""
    assert type(evidence) is LawOfOneEvidence
    assert _MINTED_EVIDENCE_IDENTITIES.get(id(evidence)) is evidence
    evidence.assert_closed()
    return evidence


_MINTED_EVIDENCE_IDENTITIES: dict[int, LawOfOneEvidence] = {}


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
) -> LawOfOneEvidence:
    """Private mint used only by ``law_of_one_auditor``."""
    evidence = object.__new__(LawOfOneEvidence)
    for name, value in locals().items():
        if name != "evidence":
            object.__setattr__(evidence, name, value)
    _MINTED_EVIDENCE_IDENTITIES[id(evidence)] = evidence
    return evidence
