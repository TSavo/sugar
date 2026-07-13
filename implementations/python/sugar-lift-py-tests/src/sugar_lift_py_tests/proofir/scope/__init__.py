from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from sugar_lift_py_tests.ir import _Atomic, _Connective, _Quantifier
from sugar_lift_py_tests.ir import Formula as IrFormula
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.formulas import (
    Formula,
    formula_from_ir,
    formula_to_rpc,
)
from sugar_lift_py_tests.proofir.sorts import Sort

if TYPE_CHECKING:
    from sugar_lift_py_tests.proofir.nodes import Provenance


@dataclass(frozen=True, init=False)
class ClosedFormula:
    formula: Formula
    allowed_vars: frozenset[str]

    def __init__(
        self,
        formula: Formula,
        *,
        allowed_vars: Iterable[str] = (),
    ) -> None:
        if not isinstance(formula, Formula):
            observed = (
                "naked ir.Formula"
                if _is_ir_formula(formula)
                else type(formula).__name__
            )
            proofir_construction_gap(
                owner="proofir.scope.ClosedFormula",
                observed=observed,
                requested="typed proofir.formulas.Formula",
                fix="construct a tiny Formula first, then install it into ClosedFormula",
            )
        allowed = frozenset(allowed_vars)
        illegal = formula.free_vars - allowed
        if illegal:
            proofir_construction_gap(
                owner="proofir.scope.ClosedFormula",
                observed=f"illegal free var(s): {', '.join(sorted(illegal))}",
                requested="formula closed under the declared scope",
                fix="declare the variable in the role scope or remove it from the formula",
            )
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "allowed_vars", allowed)

    @property
    def ir_formula(self):
        return self.formula.ir_formula


@dataclass(frozen=True, init=False)
class PostCondition:
    formula: Formula
    formals: Mapping[str, Sort]
    out_binding: str
    out_sort: Sort
    closed: ClosedFormula

    def __init__(
        self,
        formula: Formula,
        *,
        formals: Mapping[str, Sort],
        out_binding: str = "out",
        out_sort: Sort,
    ) -> None:
        _require_tiny_formula(formula, owner="proofir.scope.PostCondition")
        if out_binding not in formula.free_vars:
            proofir_construction_gap(
                owner="proofir.scope.PostCondition",
                observed=f"free vars: {', '.join(sorted(formula.free_vars))}",
                requested=f"post mentioning {out_binding!r}",
                fix="construct the post over the verifier-visible output binding",
            )
        _require_sorted_scope(
            formula,
            formals=formals,
            extra={out_binding: out_sort},
            owner="proofir.scope.PostCondition",
        )
        closed = ClosedFormula(formula, allowed_vars=(*formals.keys(), out_binding))
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "formals", dict(formals))
        object.__setattr__(self, "out_binding", out_binding)
        object.__setattr__(self, "out_sort", out_sort)
        object.__setattr__(self, "closed", closed)

    @property
    def ir_formula(self):
        return self.closed.ir_formula


@dataclass(frozen=True, init=False)
class PreCondition:
    formula: Formula
    formals: Mapping[str, Sort]
    closed: ClosedFormula

    def __init__(self, formula: Formula, *, formals: Mapping[str, Sort]) -> None:
        _require_tiny_formula(formula, owner="proofir.scope.PreCondition")
        _require_sorted_scope(
            formula,
            formals=formals,
            extra={},
            owner="proofir.scope.PreCondition",
        )
        closed = ClosedFormula(formula, allowed_vars=formals.keys())
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "formals", dict(formals))
        object.__setattr__(self, "closed", closed)

    @property
    def ir_formula(self):
        return self.closed.ir_formula


@dataclass(frozen=True, init=False)
class OpenFormula:
    formula: Formula

    def __init__(self, formula: Formula) -> None:
        _require_tiny_formula(formula, owner="proofir.scope.OpenFormula")
        object.__setattr__(self, "formula", formula)

    @property
    def ir_formula(self):
        return self.formula.ir_formula


@dataclass(frozen=True, init=False)
class ScopedFormula:
    open_formula: OpenFormula
    allowed_vars: Mapping[str, Sort]
    closed: ClosedFormula

    def __init__(
        self,
        formula: Formula | OpenFormula,
        *,
        allowed_vars: Mapping[str, Sort],
    ) -> None:
        open_formula = (
            formula if isinstance(formula, OpenFormula) else OpenFormula(formula)
        )
        _require_sorted_scope(
            open_formula.formula,
            formals=allowed_vars,
            extra={},
            owner="proofir.scope.ScopedFormula",
        )
        closed = ClosedFormula(open_formula.formula, allowed_vars=allowed_vars.keys())
        object.__setattr__(self, "open_formula", open_formula)
        object.__setattr__(self, "allowed_vars", dict(allowed_vars))
        object.__setattr__(self, "closed", closed)

    @property
    def formula(self) -> Formula:
        return self.open_formula.formula

    @property
    def ir_formula(self):
        return self.closed.ir_formula


@dataclass(frozen=True, init=False)
class ProvenancedFormula:
    scoped: ScopedFormula
    provenance: Provenance

    def __init__(self, scoped: ScopedFormula, *, provenance: Provenance) -> None:
        if not isinstance(scoped, ScopedFormula):
            proofir_construction_gap(
                owner="proofir.scope.ProvenancedFormula",
                observed=type(scoped).__name__,
                requested="ScopedFormula",
                fix="scope the formula before adding provenance",
            )
        _require_node_provenance(provenance, owner="proofir.scope.ProvenancedFormula")
        object.__setattr__(self, "scoped", scoped)
        object.__setattr__(self, "provenance", provenance)

    @property
    def formula(self) -> Formula:
        return self.scoped.formula

    @property
    def ir_formula(self):
        return self.scoped.ir_formula


@dataclass(frozen=True, init=False, eq=False)
class ClaimFormula(Mapping[str, Any]):
    """A role-wrapped formula that keeps the old wire bytes while carrying provenance."""

    provenanced: ProvenancedFormula | None
    _provenance: Provenance
    role: str
    _rpc: dict[str, Any] | None

    def __init__(self, provenanced: ProvenancedFormula, *, role: str) -> None:
        if not isinstance(provenanced, ProvenancedFormula):
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed=type(provenanced).__name__,
                requested="ProvenancedFormula",
                fix="attach construction provenance before a formula can enter a claim slot",
            )
        if not role:
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed="empty role",
                requested="claim role",
                fix="name the proof/report role that owns this formula",
            )
        object.__setattr__(self, "provenanced", provenanced)
        object.__setattr__(self, "_provenance", provenanced.provenance)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "_rpc", None)

    @classmethod
    def from_rpc(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        provenance: Provenance,
        role: str,
    ) -> ClaimFormula | None:
        if payload is None:
            return None
        _require_node_provenance(provenance, owner="proofir.scope.ClaimFormula")
        if not isinstance(payload, Mapping):
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed=type(payload).__name__,
                requested="formula RPC mapping",
                fix="deserialize a formula payload before wrapping it with claim provenance",
            )
        if not role:
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed="empty role",
                requested="claim role",
                fix="name the proof/report role that owns this formula",
            )
        wrapped = object.__new__(cls)
        object.__setattr__(wrapped, "provenanced", None)
        object.__setattr__(wrapped, "_provenance", provenance)
        object.__setattr__(wrapped, "role", role)
        object.__setattr__(wrapped, "_rpc", dict(payload))
        return wrapped

    @property
    def formula(self) -> Formula:
        if self.provenanced is None:
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed="wire-only claim formula",
                requested="constructed ProvenancedFormula",
                fix="ask the owning ProofIR node for denotation before wire lowering",
            )
        return self.provenanced.formula

    @property
    def ir_formula(self):
        if self.provenanced is None:
            proofir_construction_gap(
                owner="proofir.scope.ClaimFormula",
                observed="wire-only claim formula",
                requested="constructed ProvenancedFormula",
                fix="ask the owning ProofIR node for denotation before wire lowering",
            )
        return self.provenanced.ir_formula

    @property
    def provenance(self) -> Provenance:
        return self._provenance

    def _wire_rpc(self) -> dict[str, Any]:
        rpc = self._rpc
        if rpc is None:
            rpc = formula_to_rpc(self.formula)
            object.__setattr__(self, "_rpc", rpc)
        return rpc

    def __repr__(self) -> str:
        return repr(self._wire_rpc())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ClaimFormula):
            return self._wire_rpc() == other._wire_rpc()
        if isinstance(other, Mapping):
            return self._wire_rpc() == dict(other)
        return False

    def __getitem__(self, key: str) -> Any:
        return self._wire_rpc()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._wire_rpc())

    def __len__(self) -> int:
        return len(self._wire_rpc())

    def to_rpc(self) -> dict[str, Any]:
        return dict(self._wire_rpc())


def claim_formula_from_ir(
    ir_formula: IrFormula,
    *,
    var_sorts: Mapping[str, Sort],
    allowed_vars: Iterable[str],
    provenance: Provenance,
    role: str,
) -> ClaimFormula:
    allowed = tuple(allowed_vars)
    scoped = ScopedFormula(
        formula_from_ir(ir_formula, var_sorts=var_sorts),
        allowed_vars={name: var_sorts[name] for name in allowed},
    )
    return ClaimFormula(
        ProvenancedFormula(scoped, provenance=provenance),
        role=role,
    )


def _is_ir_formula(value: object) -> bool:
    return isinstance(value, (_Atomic, _Connective, _Quantifier))


def _require_tiny_formula(formula: object, *, owner: str) -> None:
    if isinstance(formula, Formula):
        return
    observed = "naked ir.Formula" if _is_ir_formula(formula) else type(formula).__name__
    proofir_construction_gap(
        owner=owner,
        observed=observed,
        requested="typed proofir.formulas.Formula",
        fix="construct a tiny Formula before installing it in a ProofIR role",
    )


def _require_sorted_scope(
    formula: Formula,
    *,
    formals: Mapping[str, Sort],
    extra: Mapping[str, Sort],
    owner: str,
) -> None:
    allowed_sorts = {**formals, **extra}
    illegal = formula.free_vars - set(allowed_sorts)
    if illegal:
        proofir_construction_gap(
            owner=owner,
            observed=f"illegal free var(s): {', '.join(sorted(illegal))}",
            requested="free vars only from declared formals plus out",
            fix="declare the variable in the contract scope or remove it from the formula",
        )
    unsorted = sorted(
        name for name in formula.free_vars if name not in formula.free_var_sorts
    )
    if unsorted:
        proofir_construction_gap(
            owner=owner,
            observed=f"unsorted var(s): {', '.join(unsorted)}",
            requested="every var has a sort",
            fix="wrap the ir formula with an explicit sort map before constructing the condition",
        )
    mismatched = [
        name
        for name in formula.free_vars
        if name in formula.free_var_sorts
        and name in allowed_sorts
        and formula.free_var_sorts[name] != allowed_sorts[name]
    ]
    if mismatched:
        proofir_construction_gap(
            owner=owner,
            observed=", ".join(sorted(mismatched)),
            requested="formula variable sorts match the contract scope",
            fix="use one declared sort for each formal and out binding",
        )


def _require_node_provenance(provenance: object, *, owner: str) -> None:
    from sugar_lift_py_tests.proofir.nodes import Provenance

    if not isinstance(provenance, Provenance):
        proofir_construction_gap(
            owner=owner,
            observed=type(provenance).__name__,
            requested="Provenance",
            fix="construct the formula with Stated or Derived provenance",
        )


__all__ = [
    "ClaimFormula",
    "ClosedFormula",
    "OpenFormula",
    "PostCondition",
    "PreCondition",
    "ProvenancedFormula",
    "ScopedFormula",
    "claim_formula_from_ir",
]
