from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.kit_rpc import BodyUniverseDto, FactoryWalkRowDto


def proofir_formula_provenance_diagnostic(
    contracts: list[BodyUniverseDto],
    factory_walk: list[FactoryWalkRowDto],
) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    for contract in contracts:
        for field_name in ("pre", "post", "inv"):
            if getattr(contract, field_name) is None:
                continue
            if _contract_field_has_proofir_provenance(contract):
                continue
            missing.append(
                {
                    "nodeClass": _node_class_for_contract_field(contract, field_name),
                    "constructionSite": f"{contract.name}.{field_name}",
                    "reason": "formula fragment has no typed ProofIR provenance",
                }
            )
    for row in factory_walk:
        if row.emitted_formula is None:
            continue
        missing.append(
            {
                "nodeClass": "FactoryWalkMemento",
                "constructionSite": f"{row.file}:{row.line}:{row.requested_role}",
                "reason": "factory-walk emittedFormula has no typed ProofIR provenance",
            }
        )
    return {
        "kind": "proofir-formula-provenance",
        "r": {
            "formula_fragments_without_provenance": len(missing),
            "total": len(missing),
        },
        "missing": missing,
    }


def _node_class_for_contract_field(contract: BodyUniverseDto, field_name: str) -> str:
    if contract.kind == "function-contract":
        return "FunctionContract"
    if field_name == "inv":
        return "EqualityFact"
    return "FunctionContract"


def _contract_field_has_proofir_provenance(contract: BodyUniverseDto) -> bool:
    if contract.proofir_provenance is not None:
        return True
    for warrant in contract.source_warrants:
        if isinstance(warrant, dict) and warrant.get("kind") == "proofir-provenance":
            return True
        to_rpc = getattr(warrant, "to_rpc", None)
        if callable(to_rpc):
            rpc = to_rpc()
            if isinstance(rpc, dict) and rpc.get("kind") == "proofir-provenance":
                return True
    return False
