from __future__ import annotations

from typing import Optional

from sugar_lift_py_tests.claim import SugarCandidate, SugarCatalog, SugarRole

from .factory_audit_row import FactoryAuditRow
from .factory_build_context import FactoryBuildContext
from .factory_build_result import FactoryBuildResult
from .factory_gap import FactoryGap
from .factory_gap_info import FactoryGapInfo
from .source_fragment import SourceFragment
from .source_fragment_stack import SourceFragmentStack


def build_node(
    node,
    *,
    filename: str,
    role: SugarRole,
    catalog: Optional[SugarCatalog] = None,
    ctx: Optional[FactoryBuildContext] = None,
) -> FactoryBuildResult:
    catalog = catalog or (ctx.catalog if ctx is not None else default_catalog())
    site = node if isinstance(node, SourceFragment) else SourceFragment.from_node(node, filename)
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
        role=role,
        catalog=catalog,
        ctx=ctx
        or FactoryBuildContext(
            filename=filename,
            catalog=catalog,
        ),
    )


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

    selected = _select_candidate(candidates)
    if selected is None:
        _raise_ambiguous_candidates(site, role, candidates)
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


def _select_candidate(candidates: list[SugarCandidate]) -> SugarCandidate | None:
    if len(candidates) == 1:
        return candidates[0]
    if len({candidate.name for candidate in candidates}) != len(candidates):
        return None

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
) -> None:
    names = [candidate.name for candidate in candidates]
    info = FactoryGapInfo(
        owner="python.factory",
        blame=site.blame,
        observed=f"{site.observed} candidates=[{', '.join(names)}]",
        requested=role.value,
        fix="declare comes_before or split the sugar role",
        gap_kind="Sugar ordering",
        gap_locus="AST",
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
    from sugar_lift_py_tests.sugar.array_literal_sugar import ARRAY_LITERAL_CLAIM
    from sugar_lift_py_tests.sugar.binop_sugar import BINOP_CLAIM
    from sugar_lift_py_tests.sugar.bitwise_op_sugar import BITWISE_OP_CLAIM
    from sugar_lift_py_tests.sugar.name_sugar import NAME_CLAIM
    from sugar_lift_py_tests.sugar.primitive_literal_sugar import (
        PRIMITIVE_LITERAL_CLAIM,
    )
    from sugar_lift_py_tests.sugar.assign_sugar import ASSIGN_CLAIM
    from sugar_lift_py_tests.sugar.block_sugar import BLOCK_CLAIM
    from sugar_lift_py_tests.sugar.if_sugar import IF_CLAIM
    from sugar_lift_py_tests.sugar.ord_sugar import ORD_BYTE_CLAIM
    from sugar_lift_py_tests.sugar.return_sugar import RETURN_CLAIM
    from sugar_lift_py_tests.sugar.string_subscript_sugar import STRING_SUBSCRIPT_CLAIM

    # Self-registering Sugar subclasses (migrated to the base class) contribute their
    # claims by import side effect; the legacy CLAIM constants below are the not-yet-
    # migrated sugars and are folded in until they move onto the base too.
    from sugar_lift_py_tests.sugar import comment_sugar  # noqa: F401  registers CommentSugar
    from sugar_lift_py_tests.sugar.sugar_base import registered_claims

    return SugarCatalog(
        [
            *registered_claims(),
            PRIMITIVE_LITERAL_CLAIM,
            BITWISE_OP_CLAIM,
            ARRAY_LITERAL_CLAIM,
            BINOP_CLAIM,
            NAME_CLAIM,
            STRING_SUBSCRIPT_CLAIM,
            BLOCK_CLAIM,
            RETURN_CLAIM,
            ASSIGN_CLAIM,
            IF_CLAIM,
            ORD_BYTE_CLAIM,
        ]
    )
