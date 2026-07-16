from __future__ import annotations

import ast
from collections.abc import Mapping

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.factory_gap_info import (
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment

_GENERIC_COORDINATE_CLAIMS = frozenset(
    {"CallSugar", "KeywordCallSugar", "MethodCallSugar"}
)


def universe_coverage_gaps(
    payload,
    *,
    module,
    catalog,
    filename: str,
) -> list[FactoryGapInfo]:
    """Name asserted call edges for which no universe recipe testified.

    This is an audit over already-completed testimony. It neither changes the
    fact/call-edge payload nor constructs an Outcome arm.
    """
    body_symbols = {
        symbol
        for contract in payload.ir
        if contract.post is not None
        for symbol in _contract_symbols(contract)
    }
    call_nodes = _call_nodes_by_locus(module, filename)
    gaps: list[FactoryGapInfo] = []
    seen: set[tuple[str, str, int, int]] = set()
    for edge in payload.call_edges:
        source_contract = str(edge.get("sourceContract") or "")
        if not _assertion_source_contract(source_contract):
            continue
        target = str(edge.get("targetSymbol") or "")
        locus = edge.get("callSiteLocus")
        if not target or not isinstance(locus, Mapping):
            continue
        file = str(locus.get("file") or filename)
        line = int(locus.get("line") or 0)
        col = int(locus.get("col") or locus.get("column") or 0)
        key = (target, file, line, col)
        if key in seen:
            continue
        seen.add(key)
        callee = _callee_name(target)
        if callee in body_symbols:
            continue
        if _edge_carries_external_universe(edge):
            continue
        node = call_nodes.get((line, col))
        if node is not None and _has_builtin_universe_claim(
            node, catalog=catalog, filename=filename
        ):
            continue
        blame = f"{file}:{line}:{col}"
        gaps.append(
            FactoryGapInfo(
                owner="python.factory",
                blame=blame,
                observed=target,
                requested="callee universe coverage",
                fix=(
                    "add builtin-universe recognizer / dig body / add bridge "
                    "coverage / load vendor proof"
                ),
                gap_kind=GapKind.SUGAR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
    return gaps


def universe_absence_reason(info: FactoryGapInfo) -> str:
    return (
        f"{info.message}; no universe sugar for callee {info.observed}: "
        "no diggable body, no builtin-universe recognizer claim, "
        "no bridge-borne contract, no loaded vendor proof"
    )


def _assertion_source_contract(source_contract: str) -> bool:
    leaf = source_contract.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return leaf.startswith("test_") or leaf == "<module>"


def _contract_symbols(contract) -> set[str]:
    symbols = {contract.name}
    if contract.bridge_source_symbol:
        symbols.add(contract.bridge_source_symbol)
    return symbols


def _callee_name(target: str) -> str:
    return target.split(":", 1)[1] if ":" in target else target


def _edge_carries_external_universe(edge: Mapping[str, object]) -> bool:
    return any(
        edge.get(field)
        for field in (
            "targetContract",
            "targetContractCid",
            "targetProofCid",
        )
    )


def _call_nodes_by_locus(
    module, filename: str
) -> dict[tuple[int, int], SourceFragment]:
    root = module.node if isinstance(module, SourceFragment) else module
    if not isinstance(root, ast.AST):
        root = ast.Module(body=list(root.body), type_ignores=[])
    return {
        (int(node.lineno), int(node.col_offset)): SourceFragment.from_node(
            node, filename
        )
        for node in ast.walk(root)
        if isinstance(node, ast.Call)
    }


def _has_builtin_universe_claim(site, *, catalog, filename: str) -> bool:
    del filename
    names = {
        candidate.name for candidate in catalog.candidates_for(SugarRole.TERM, site)
    }
    return bool(names - _GENERIC_COORDINATE_CLAIMS)


__all__ = ["universe_absence_reason", "universe_coverage_gaps"]
