"""Join collapse-projected call edges to imported contract bindings.

CallSiteValue.edge_contribution emits seal-free edges (kind / sourceContract /
targetSymbol / locus only). The mint/report second pass feeds dependency
`contract_bindings` so this join can stamp targetContract, targetContractCid,
and targetProofCid without inventing CIDs on the first (producer) pass.

Symbol match restores the #3668 candidates: `call:sum` / `method:sum` / bare
`sum` all join a vendor binding whose bridgeSourceSymbol is `call:sum` (or
the bare/public spelling). Prefixes are never invented for emission — only
matched for join.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence


def resolve_call_edges_against_bindings(
    edges: Sequence[Mapping[str, Any]],
    contract_bindings: Sequence[Any],
) -> list[dict[str, Any]]:
    """Return edges with import seal fields filled when a binding matches.

    Unmatched edges are cloned unchanged. Seal fields already present on an
    edge win over a re-join (never downgrade a resolved edge).
    """
    resolved: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        out = dict(edge)
        if out.get("kind") not in (None, "call-edge"):
            resolved.append(out)
            continue
        target_symbol = out.get("targetSymbol") or out.get("target_symbol")
        if not isinstance(target_symbol, str) or not target_symbol:
            resolved.append(out)
            continue
        if _edge_already_sealed(out):
            resolved.append(out)
            continue
        binding = binding_for_bridge_symbol(contract_bindings, target_symbol)
        if binding is None:
            resolved.append(out)
            continue
        stamp_edge_from_binding(out, binding)
        resolved.append(out)
    return resolved


def stamp_edge_from_binding(
    edge: MutableMapping[str, Any], binding: Mapping[str, Any]
) -> None:
    """Mutate `edge` with the seal fields the binding authorizes."""
    name = binding.get("name")
    if isinstance(name, str) and name and not edge.get("targetContract"):
        edge["targetContract"] = name
    cid = binding_contract_cid(binding)
    if cid is not None and not edge.get("targetContractCid"):
        edge["targetContractCid"] = cid
    proof_cid = binding_proof_cid(binding)
    if proof_cid is not None and not edge.get("targetProofCid"):
        edge["targetProofCid"] = proof_cid


def binding_for_bridge_symbol(
    contract_bindings: Sequence[Any],
    target_symbol: str,
) -> dict[str, Any] | None:
    target_symbols = bridge_symbol_match_candidates(target_symbol)
    for binding in contract_bindings:
        if not isinstance(binding, Mapping):
            continue
        if binding_bridge_candidates(binding) & target_symbols:
            return dict(binding)
    return None


def bridge_symbol_match_candidates(target_symbol: str) -> set[str]:
    candidates = {target_symbol}
    if target_symbol.startswith("call:"):
        candidates.add(target_symbol.removeprefix("call:"))
    if target_symbol.startswith("method:"):
        method_name = target_symbol.removeprefix("method:")
        candidates.add(method_name)
        # Method edges still join call:<method> vendor spellings (#3668).
        candidates.add(f"call:{method_name}")
    return {candidate for candidate in candidates if candidate}


def binding_bridge_candidates(binding: Mapping[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("bridgeSourceSymbol", "name"):
        value = binding.get(key)
        if not isinstance(value, str) or not value:
            continue
        candidates.add(value)
        if value.startswith("call:"):
            candidates.add(value.removeprefix("call:"))
        elif not value.startswith("method:"):
            candidates.add(f"call:{value}")
    for library in binding_libraries(binding):
        for value in tuple(candidates):
            if value.startswith(("call:", "method:")):
                continue
            if value == library or value.startswith(f"{library}."):
                continue
            candidates.add(f"{library}.{value}")
            candidates.add(f"call:{library}.{value}")
    # Leaf expansion: binding `numpy.load` / `call:numpy.load` also answers
    # an edge projected as bare `call:load` (import alias collapsed on the
    # callsite). Suffix-only — never invent a library for an edge leaf.
    for value in tuple(candidates):
        bare = value
        if bare.startswith("call:"):
            bare = bare.removeprefix("call:")
        elif bare.startswith("method:"):
            bare = bare.removeprefix("method:")
        if "." in bare:
            leaf = bare.rsplit(".", 1)[-1]
            if leaf:
                candidates.add(leaf)
                candidates.add(f"call:{leaf}")
    return candidates


def binding_libraries(binding: Mapping[str, Any]) -> tuple[str, ...]:
    libraries: list[str] = []
    for key in ("library", "library_tag", "target_library_tag", "targetLibraryTag"):
        value = binding.get(key)
        if isinstance(value, str) and value:
            libraries.append(value)
    return tuple(dict.fromkeys(libraries))


def binding_contract_cid(binding: Mapping[str, Any] | None) -> str | None:
    if binding is None:
        return None
    cid = (
        binding.get("contract_cid")
        or binding.get("contractCid")
        or binding.get("targetContractCid")
    )
    return cid if isinstance(cid, str) and cid else None


def binding_proof_cid(binding: Mapping[str, Any] | None) -> str | None:
    if binding is None:
        return None
    cid = binding.get("target_proof_cid") or binding.get("targetProofCid")
    return cid if isinstance(cid, str) and cid else None


def _edge_already_sealed(edge: Mapping[str, Any]) -> bool:
    cid = edge.get("targetContractCid") or edge.get("target_contract_cid")
    return isinstance(cid, str) and bool(cid.strip())


__all__ = [
    "binding_bridge_candidates",
    "binding_contract_cid",
    "binding_for_bridge_symbol",
    "binding_libraries",
    "binding_proof_cid",
    "bridge_symbol_match_candidates",
    "resolve_call_edges_against_bindings",
    "stamp_edge_from_binding",
]
