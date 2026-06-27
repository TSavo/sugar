from __future__ import annotations

from typing import Optional

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole

from .factory_audit_row import FactoryAuditRow
from .factory_build_context import FactoryBuildContext
from .factory_build_result import FactoryBuildResult
from .factory_gap import FactoryGap
from .factory_gap_info import FactoryGapInfo
from .source_site import SourceSite
from .source_site_stack import SourceSiteStack


def build_node(
    node,
    *,
    filename: str,
    role: SugarRole,
    catalog: Optional[SugarCatalog] = None,
    ctx: Optional[FactoryBuildContext] = None,
) -> FactoryBuildResult:
    catalog = catalog or (ctx.catalog if ctx is not None else default_catalog())
    return _build_site(
        SourceSite.from_node(node, filename),
        role=role,
        catalog=catalog,
        ctx=ctx
        or FactoryBuildContext(
            filename=filename,
            catalog=catalog,
        ),
    )


def build_next(
    source: str,
    filename: str,
    role: SugarRole,
    catalog: Optional[SugarCatalog] = None,
    ctx: Optional[FactoryBuildContext] = None,
) -> FactoryBuildResult:
    site = SourceSiteStack.from_source(source, filename).pop()
    if site is None:
        raise ValueError("factory source contained no source sites")

    catalog = catalog or (ctx.catalog if ctx is not None else default_catalog())
    return _build_site(
        site,
        role=role,
        catalog=catalog,
        ctx=ctx
        or FactoryBuildContext(
            filename=filename,
            catalog=catalog,
        ),
    )


def _build_site(
    site: SourceSite,
    *,
    role: SugarRole,
    catalog: SugarCatalog,
    ctx: FactoryBuildContext,
) -> FactoryBuildResult:
    candidates = catalog.candidates_for(role, site)
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
    sugar = selected.claim.build(site, ctx)
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


def default_catalog() -> SugarCatalog:
    from sugar_lift_py_tests.sugar.array_literal_sugar import ARRAY_LITERAL_CLAIM
    from sugar_lift_py_tests.sugar.bitwise_op_sugar import BITWISE_OP_CLAIM
    from sugar_lift_py_tests.sugar.primitive_literal_sugar import (
        PRIMITIVE_LITERAL_CLAIM,
    )

    return SugarCatalog([PRIMITIVE_LITERAL_CLAIM, BITWISE_OP_CLAIM, ARRAY_LITERAL_CLAIM])
