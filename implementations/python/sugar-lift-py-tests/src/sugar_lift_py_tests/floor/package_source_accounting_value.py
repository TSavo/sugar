from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.kit_rpc import SourceAuditDto

from .floor_value import FloorValue


@dataclass(frozen=True)
class PackageSourceAccountingValue(FloorValue):
    """Cited, non-FOL structural testimony for imported package sources."""

    non_fol_support = True
    source_audits: tuple[SourceAuditDto, ...]
