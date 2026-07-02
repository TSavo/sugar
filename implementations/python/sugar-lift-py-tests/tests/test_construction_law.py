from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.ir import (
    eq as ir_eq,
    formula_to_value,
    make_var,
    num,
)
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.proofir import (
    ConstructionSite,
    Derived,
    EqualityFact,
    Provenance,
    RefusalRecord,
    canonical_euf_callsite_name,
)
from sugar_lift_py_tests.proofir.formulas import Eq
from sugar_lift_py_tests.proofir.scope import ClosedFormula
from sugar_lift_py_tests.proofir.sorts import IntSort, StringSort
from sugar_lift_py_tests.proofir.terms import CallTerm, ConstTerm, VarTerm

ROOT = Path(__file__).resolve().parents[4]


def _provenance() -> Provenance:
    site = ConstructionSite(path="tests/test_construction_law.py", line=1)
    return Provenance(
        node_class="EqualityFact",
        construction_site=site,
        warrant=Derived(floor_chain=("construction-law",)),
    )


def test_eq_refuses_wrong_sort_terms() -> None:
    call = CallTerm("h", (), sort=IntSort())
    rhs = ConstTerm("not-an-int", sort=StringSort())

    with pytest.raises(FactoryGap, match="matching sorts"):
        Eq(call, rhs)


def test_closed_formula_refuses_naked_ir_formula_and_illegal_free_var() -> None:
    out = VarTerm("out", sort=IntSort())
    ghost = VarTerm("ghost", sort=IntSort())

    with pytest.raises(FactoryGap, match="naked ir.Formula"):
        ClosedFormula(ir_eq(make_var("out"), num(0)))

    with pytest.raises(FactoryGap, match="illegal free var"):
        ClosedFormula(Eq(out, ghost), allowed_vars=("out",))


def test_equality_fact_derives_key_and_preserves_wire_bytes() -> None:
    call = CallTerm("h", (ConstTerm(5, sort=IntSort()),), sort=IntSort())
    rhs = ConstTerm(6, sort=IntSort())
    fact = EqualityFact(call_term=call, rhs_term=rhs, provenance=_provenance())

    expected_inv = json.loads(encode_jcs(formula_to_value(ir_eq(call.ir_term, rhs.ir_term))))
    expected_name = canonical_euf_callsite_name(call)
    expected_declaration = BodyUniverseDto(
        name=expected_name,
        out_binding="out",
        inv=expected_inv,
        proofir_provenance=fact.provenance().warrant_memento(),
    ).to_rpc()

    assert fact.euf_key == expected_name
    assert repr(fact.denotation()) == repr(ir_eq(call.ir_term, rhs.ir_term))
    assert fact.to_declaration() == expected_declaration
    assert json.loads(fact.to_proof_ir()) == expected_declaration


def test_equality_fact_from_string_key_is_unrepresentable() -> None:
    call = CallTerm("h", (), sort=IntSort())
    rhs = ConstTerm(0, sort=IntSort())

    with pytest.raises(TypeError, match="euf_key"):
        EqualityFact(
            euf_key="free-typed-key",
            call_term=call,
            rhs_term=rhs,
            provenance=_provenance(),
        )


def test_naked_formula_cannot_be_inserted_as_equality_fact_term() -> None:
    call = CallTerm("h", (), sort=IntSort())
    rhs = ConstTerm(0, sort=IntSort())

    with pytest.raises(FactoryGap, match="CallTerm"):
        EqualityFact(
            call_term=Eq(call, rhs),
            rhs_term=rhs,
            provenance=_provenance(),
        )


def test_refusal_record_stays_disjoint_from_predicates() -> None:
    with pytest.raises(FactoryGap, match="formula and refusal"):
        RefusalRecord.from_incomplete(
            Incomplete(RuntimeEffect("opaque runtime effect")),
            provenance=Provenance(
                node_class="RefusalRecord",
                construction_site=ConstructionSite(
                    path="tests/test_construction_law.py",
                    line=1,
                ),
                warrant=Derived(floor_chain=("construction-law",)),
            ),
            formula=ir_eq(make_var("call"), num(0)),
        )
