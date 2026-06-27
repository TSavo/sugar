from __future__ import annotations

from typing import Optional

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole

from .factory_audit_row import FactoryAuditRow
from .factory_build_result import FactoryBuildResult
from .factory_gap import FactoryGap
from .factory_gap_info import FactoryGapInfo
from .source_site_stack import SourceSiteStack


def build_next(
    source: str,
    filename: str,
    role: SugarRole,
    catalog: Optional[SugarCatalog] = None,
) -> FactoryBuildResult:
    site = SourceSiteStack.from_source(source, filename).pop()
    if site is None:
        raise ValueError("factory source contained no source sites")

    sugar_catalog = catalog or SugarCatalog()
    candidates = sugar_catalog.candidates_for(role, site)
    if not candidates:
        info = FactoryGapInfo(
            owner="python.factory",
            blame=site.blame,
            observed=site.observed,
            requested=role.value,
            fix=f"create {site.suggested_sugar_module}",
        )
        audit_row = FactoryAuditRow(
            role=role.value,
            status="sugar-gap",
            observed=site.observed,
            blame=site.blame,
            selected=None,
            candidates=[],
            message=info.message,
        )
        raise FactoryGap(info, audit_row)

    selected = candidates[0]
    sugar = selected.claim.build(site)
    message = f"selected Sugar `{selected.name}` for role {role.value} at `{site.blame}`"
    audit_row = FactoryAuditRow(
        role=role.value,
        status="selected",
        observed=site.observed,
        blame=site.blame,
        selected=selected.name,
        candidates=[candidate.name for candidate in candidates],
        message=message,
    )
    return FactoryBuildResult(sugar=sugar, audit_row=audit_row)
