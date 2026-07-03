from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.proofir import FunctionContract


@dataclass(frozen=True)
class FloorContractAgreementViolation:
    callee: str
    contract: str
    callsite: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "floor-contract-agreement-violation",
            "callee": self.callee,
            "contract": self.contract,
            "callsite": self.callsite,
            "reason": self.reason,
        }


def floor_contract_agreement_diagnostic(
    violations: list[FloorContractAgreementViolation],
) -> dict[str, Any]:
    return {
        "kind": "floor-contract-agreement",
        "r": {
            "agreement_violations": len(violations),
            "total": len(violations),
        },
        "violations": [violation.to_json() for violation in violations],
    }


def enforce_floor_contract_agreement_gate(
    violations: list[FloorContractAgreementViolation],
) -> None:
    if not violations:
        return
    rows = [
        f"{violation.callee}: {violation.contract} vs {violation.callsite}: {violation.reason}"
        for violation in violations
    ]
    raise RuntimeError(
        "floor-contract agreement gate red: "
        f"R(agreement-violations)={len(violations)}\n" + "\n".join(rows)
    )


def floor_contract_agreement_violations_for_fact(
    *,
    callee: str,
    callable_contract: FunctionContract,
    arg_terms: list[Term],
    floor_term: Term,
    callsite_contract: str,
) -> list[FloorContractAgreementViolation]:
    verdict = callable_contract.floor_models_post(
        arg_terms=arg_terms,
        floor_term=floor_term,
    )
    if verdict is not False:
        return []
    return [
        FloorContractAgreementViolation(
            callee=callee,
            contract=callable_contract.symbol,
            callsite=callsite_contract,
            reason="derived floor does not model callable post",
        )
    ]
