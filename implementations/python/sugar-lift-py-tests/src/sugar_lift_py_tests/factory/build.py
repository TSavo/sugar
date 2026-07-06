from __future__ import annotations

import ast
from typing import NoReturn, Optional

from sugar_lift_py_tests.claim import SugarCandidate, SugarCatalog, SugarRole

from .factory_audit_row import FactoryAuditRow
from .factory_build_context import FactoryBuildContext
from .factory_build_result import FactoryBuildResult
from .factory_gap import FactoryGap
from .factory_gap_info import FactoryGapInfo, GapKind, GapLocus
from .source_fragment import SourceFragment
from .source_fragment_stack import SourceFragmentStack
from sugar_lift_py_tests.sugar_body import ReducibleSugar


class FactoryCandidateDeclined(RuntimeError):
    """A selected sugar can step aside only so the factory can select the next one."""


def build_node(
    node: ast.AST | SourceFragment | None,
    *,
    filename: str,
    role: SugarRole,
    catalog: Optional[SugarCatalog] = None,
    ctx: Optional[FactoryBuildContext] = None,
) -> FactoryBuildResult:
    catalog = catalog or (ctx.catalog if ctx is not None else default_catalog())
    site = (
        node
        if isinstance(node, SourceFragment)
        else SourceFragment.from_node(node, filename)
    )
    return _build_site(
        site,
        role=_fallback_role(site, role),
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
    memento_file: str | None = None,
    catalog: Optional[SugarCatalog] = None,
    ctx: Optional[FactoryBuildContext] = None,
    contract_bindings: list | None = None,
) -> FactoryBuildResult | object:
    report = _build_source_report(
        source=source,
        filename=filename,
        memento_file=memento_file,
        contract_bindings=contract_bindings,
    )
    if report is not None:
        return report

    site = SourceFragmentStack.from_source(source, filename).pop()
    if site is None:
        raise ValueError("factory source contained no source sites")

    catalog = catalog or (ctx.catalog if ctx is not None else default_catalog())
    return _build_site(
        site,
        role=_fallback_role(site, role),
        catalog=catalog,
        ctx=ctx
        or FactoryBuildContext(
            filename=filename,
            catalog=catalog,
        ),
    )


def _fallback_role(site: SourceFragment, requested: SugarRole) -> SugarRole:
    if requested == SugarRole.TERM and site.is_statement_site():
        return SugarRole.STATEMENT
    return requested


def _build_source_report(
    *,
    source: str,
    filename: str,
    memento_file: str | None,
    contract_bindings: list | None = None,
):
    from .array_map_report import build_array_map_report
    from .literal_call_report import build_literal_call_report

    array_map = build_array_map_report(
        source=source,
        filename=filename,
        memento_file=memento_file,
    )
    if array_map is not None:
        return array_map
    return build_literal_call_report(
        source=source,
        filename=filename,
        memento_file=memento_file,
        contract_bindings=contract_bindings,
    )


def _build_site(
    site: SourceFragment,
    *,
    role: SugarRole,
    catalog: SugarCatalog,
    ctx: FactoryBuildContext,
    excluded: frozenset[str] = frozenset(),
) -> FactoryBuildResult:
    candidates = [
        candidate
        for candidate in catalog.candidates_for(role, site)
        if candidate.name not in excluded
    ]
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

    selected = _select_candidate(candidates)
    if selected is None:
        _raise_ambiguous_candidates(site, role, candidates)
    try:
        sugar = selected.claim.build(site, ctx)
    except FactoryCandidateDeclined:
        return _build_site(
            site,
            role=role,
            catalog=catalog,
            ctx=ctx,
            excluded=excluded | {selected.name},
        )
    message = (
        f"selected Sugar `{selected.name}` for role {role.value} at `{site.blame}`"
    )
    audit_row = FactoryAuditRow(
        role=role.value,
        status="selected",
        observed=site.observed,
        blame=site.blame,
        selected=selected.name,
        candidates=[candidate.name for candidate in candidates],
        message=message,
    )
    if ctx.audit_sink is not None:
        ctx.audit_sink.append(audit_row.to_json())
    if not isinstance(sugar, ReducibleSugar):
        raise TypeError(
            "Factory selected a non-reducible Sugar product: "
            f"owner=factory.build illegal={type(sugar).__name__} "
            "replacement=Sugar or ReducibleSugar"
        )
    return FactoryBuildResult(sugar=sugar, audit_row=audit_row)


def _select_candidate(candidates: list[SugarCandidate]) -> SugarCandidate | None:
    if len(candidates) == 1:
        return candidates[0]

    by_name = {candidate.name: candidate for candidate in candidates}
    winners = [
        candidate
        for candidate in candidates
        if all(
            candidate.name == other.name
            or _dominates(candidate, other, by_name, seen=frozenset())
            for other in candidates
        )
    ]
    if len(winners) != 1:
        return None
    return winners[0]


def _dominates(
    left: SugarCandidate,
    right: SugarCandidate,
    by_name: dict[str, SugarCandidate],
    *,
    seen: frozenset[str],
) -> bool:
    if left.name in seen:
        return False
    next_seen = seen | {left.name}
    for next_name in left.claim.comes_before:
        if next_name == right.name:
            return True
        next_candidate = by_name.get(next_name)
        if next_candidate is not None and _dominates(
            next_candidate,
            right,
            by_name,
            seen=next_seen,
        ):
            return True
    return False


def _raise_ambiguous_candidates(
    site: SourceFragment, role: SugarRole, candidates: list[SugarCandidate]
) -> NoReturn:
    names = [candidate.name for candidate in candidates]
    info = FactoryGapInfo(
        owner="python.factory",
        blame=site.blame,
        observed=f"{site.observed} candidates=[{', '.join(names)}]",
        requested=role.value,
        fix="declare comes_before or split the sugar role",
        gap_kind=GapKind.SUGAR_ORDERING,
        gap_locus=GapLocus.AST,
    )
    audit_row = FactoryAuditRow(
        role=role.value,
        status="sugar-ambiguous",
        observed=site.observed,
        blame=site.blame,
        selected=None,
        candidates=names,
        message=info.message,
    )
    raise FactoryGap(info, audit_row)


def default_catalog() -> SugarCatalog:
    # Import every sugar module so each class self-registers (via __init_subclass__),
    # then the catalog is ALL of them -- no whitelist. When more than one sugar owns a
    # fragment, the factory sorts the matching candidates by `comes_before` (declared on
    # the sugar) and takes the winner; that precedence lives on the sugar, not here.
    import importlib
    import pkgutil

    from sugar_lift_py_tests import sugar as _sugar_pkg
    from sugar_lift_py_tests.sugar.sugar_base import (
        registered_claims,
        validate_registry,
    )

    for _mod in pkgutil.iter_modules(_sugar_pkg.__path__):
        importlib.import_module(f"sugar_lift_py_tests.sugar.{_mod.name}")
    validate_registry()
    return SugarCatalog(registered_claims())
