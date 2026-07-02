from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import Term, term_to_value
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto


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
    callable_contract: BodyUniverseDto,
    arg_terms: list[Term],
    floor_term: Term,
    callsite_contract: str,
) -> list[FloorContractAgreementViolation]:
    if callable_contract.post is None:
        return []
    env = {
        name: _term_to_rpc(term)
        for name, term in zip(callable_contract.formals, arg_terms)
    }
    env["out"] = _term_to_rpc(floor_term)
    verdict = _formula_models(callable_contract.post, env)
    if verdict is not False:
        return []
    return [
        FloorContractAgreementViolation(
            callee=callee,
            contract=callable_contract.name,
            callsite=callsite_contract,
            reason="derived floor does not model callable post",
        )
    ]


def _formula_models(formula: dict[str, Any], env: dict[str, Any]) -> bool | None:
    kind = formula.get("kind")
    if kind == "atomic" and formula.get("name") == "=":
        args = formula.get("args")
        if not isinstance(args, list) or len(args) != 2:
            return None
        left = _normalize_term(args[0], env)
        right = _normalize_term(args[1], env)
        return left == right if left is not None and right is not None else None
    if kind == "and":
        operands = formula.get("operands")
        if not isinstance(operands, list):
            return None
        verdicts = [_formula_models(operand, env) for operand in operands]
        if any(verdict is False for verdict in verdicts):
            return False
        if all(verdict is True for verdict in verdicts):
            return True
        return None
    return None


def _normalize_term(term: Any, env: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(term, dict):
        return None
    kind = term.get("kind")
    if kind == "var":
        name = term.get("name")
        return env.get(name) if isinstance(name, str) else None
    if kind == "const":
        return term
    if kind != "ctor":
        return None
    name = term.get("name")
    args = term.get("args")
    if not isinstance(name, str) or not isinstance(args, list):
        return None
    normalized_args = [_normalize_term(arg, env) for arg in args]
    if any(arg is None for arg in normalized_args):
        return None
    normalized = {"kind": "ctor", "name": name, "args": normalized_args}
    folded = _fold_ctor(name, normalized_args)
    return folded if folded is not None else normalized


def _fold_ctor(name: str, args: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    if name not in {"+", "-", "*"}:
        return None
    if not all(_is_int_const(arg) for arg in args):
        return None
    values = [int(arg["value"]) for arg in args if arg is not None]
    if name == "+":
        value = sum(values)
    elif name == "*":
        value = 1
        for item in values:
            value *= item
    elif name == "-" and len(values) == 1:
        value = -values[0]
    elif name == "-" and len(values) == 2:
        value = values[0] - values[1]
    else:
        return None
    return {
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": "Int"},
    }


def _is_int_const(term: dict[str, Any] | None) -> bool:
    return (
        isinstance(term, dict)
        and term.get("kind") == "const"
        and isinstance(term.get("value"), int)
        and not isinstance(term.get("value"), bool)
        and term.get("sort") == {"kind": "primitive", "name": "Int"}
    )


def _term_to_rpc(term: Term) -> dict[str, Any]:
    return json.loads(encode_jcs(term_to_value(term)))
