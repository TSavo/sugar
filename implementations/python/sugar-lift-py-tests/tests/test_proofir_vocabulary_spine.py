from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import euf_call_term, euf_callsite_name
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.ir import (
    Bool,
    Formula,
    Int,
    PrimitiveSort,
    Sort,
    Term,
    _Atomic,
    _Connective,
    _ConstBool,
    _ConstInt,
    _ConstStr,
    _Ctor,
    _Quantifier,
    _Var,
    bool_const,
    eq,
    make_var,
    num,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.idd.proofir_vocab_instruments import (
    collect_proofir_vocabulary_frontier,
)
from sugar_lift_py_tests.proofir import (
    ConstructionSite,
    Derived,
    EqualityFact,
    FunctionContract,
    Provenance,
    RefusalRecord,
    Stated,
    canonical_euf_callsite_name,
)


ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class _SolverCase:
    formulas: tuple[Formula, ...]
    declarations: dict[str, Sort]


def _construction_site() -> ConstructionSite:
    return ConstructionSite(path="tests/proofir_spine.py", line=7, column=3)


def _stated_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=Stated(locus=_construction_site()),
    )


def _derived_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=Derived(floor_chain=("CallSiteValue.force_floor",)),
    )


def _two_warrant_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=(
            Stated(locus=_construction_site()),
            Derived(floor_chain=("CallSiteValue.force_floor",)),
        ),
    )


def _z3_status(case: _SolverCase) -> str:
    declarations = "\n".join(
        f"(declare-const {_smt_name(name)} {_smt_sort(sort)})"
        for name, sort in sorted(case.declarations.items())
    )
    assertions = "\n".join(f"(assert {_smt_formula(formula)})" for formula in case.formulas)
    smt = f"{declarations}\n{assertions}\n(check-sat)\n"
    completed = subprocess.run(
        ["z3", "-in"],
        input=smt,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.splitlines()[0]


def _smt_sort(sort: Sort) -> str:
    if isinstance(sort, PrimitiveSort):
        if sort.name in {"Int", "Bool", "String", "Real"}:
            return sort.name
    raise AssertionError(f"test solver harness does not support sort {sort!r}")


def _smt_formula(formula: Formula) -> str:
    if isinstance(formula, _Atomic):
        if formula.name == "=" and len(formula.args) == 2:
            return f"(= {_smt_term(formula.args[0])} {_smt_term(formula.args[1])})"
        raise AssertionError(f"unsupported atomic formula in witness: {formula!r}")
    if isinstance(formula, _Connective):
        rendered = [_smt_formula(operand) for operand in formula.operands]
        if formula.kind == "and":
            return "(and true)" if not rendered else f"(and {' '.join(rendered)})"
        if formula.kind == "implies" and len(rendered) == 2:
            return f"(=> {rendered[0]} {rendered[1]})"
        if formula.kind == "not" and len(rendered) == 1:
            return f"(not {rendered[0]})"
        raise AssertionError(f"unsupported connective in witness: {formula!r}")
    if isinstance(formula, _Quantifier):
        return (
            f"({formula.kind} (({_smt_name(formula.name)} {_smt_sort(formula.sort)})) "
            f"{_smt_formula(formula.body)})"
        )
    raise AssertionError(f"unsupported formula in witness: {formula!r}")


def _smt_term(term: Term) -> str:
    if isinstance(term, _ConstInt):
        return str(term.value)
    if isinstance(term, _ConstBool):
        return "true" if term.value else "false"
    if isinstance(term, _ConstStr):
        return '"' + term.value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(term, _Var):
        return _smt_name(term.name)
    if isinstance(term, _Ctor):
        return _smt_name(term.name if not term.args else repr(term))
    raise AssertionError(f"unsupported term in witness: {term!r}")


def _smt_name(name: str) -> str:
    return "|proofir:" + name.replace("|", "_") + "|"


def _run_witness_case(case) -> str:
    return _z3_status(_SolverCase(case.formulas, dict(case.declarations)))


def test_instrument_c_registers_the_three_spine_witness_classes() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.proofir_classes_without_verdict_witnesses == 4
    assert report.verdict_witnesses.missing_classes == [
        "CallEdgeDecl",
        "AuditMemento",
        "UniverseMint",
        "VendorConjoin",
    ]


def test_equality_fact_truthful_and_lying_witnesses_hit_real_solver() -> None:
    pair = EqualityFact.verdict_witnesses()

    assert _run_witness_case(pair.truthful) == "sat"
    assert _run_witness_case(pair.lying) == "unsat"


def test_equality_fact_constructor_invariants_are_loud() -> None:
    call_term = euf_call_term("h", [num(5)])
    good_key = canonical_euf_callsite_name(call_term)
    assert good_key == euf_callsite_name("h", call_term, suffix="::assertion")

    fact = EqualityFact(
        euf_key=good_key,
        call_term=call_term,
        rhs_term=num(5),
        provenance=_two_warrant_provenance("EqualityFact"),
    )
    assert fact.denotation() == eq(call_term, num(5))
    assert len(fact.provenance().warrants) == 2
    assert fact.cid().startswith("blake3-512:")

    with pytest.raises(FactoryGap, match="euf_key"):
        EqualityFact(
            euf_key="free-typed-key",
            call_term=call_term,
            rhs_term=num(5),
            provenance=_stated_provenance("EqualityFact"),
        )
    with pytest.raises(FactoryGap, match="rhs_term must be a typed Term"):
        EqualityFact(
            euf_key=good_key,
            call_term=call_term,
            rhs_term={"kind": "const"},
            provenance=_stated_provenance("EqualityFact"),
        )


def test_function_contract_witnesses_and_builder_invariants() -> None:
    pair = FunctionContract.verdict_witnesses()

    assert _run_witness_case(pair.truthful) == "sat"
    assert _run_witness_case(pair.lying) == "unsat"

    contract = (
        FunctionContract.builder(
            symbol="module::f::callable",
            out_binding="out",
            out_sort=Int(),
            provenance=_derived_provenance("FunctionContract"),
        )
        .formal("x", Int())
        .post(eq(make_var("out"), make_var("x")))
        .build()
    )
    assert contract.denotation() is not None
    assert contract.cid().startswith("blake3-512:")

    with pytest.raises(FactoryGap, match="post"):
        (
            FunctionContract.builder(
                symbol="module::missing::callable",
                out_binding="out",
                out_sort=Int(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .formal("x", Int())
            .build()
        )
    with pytest.raises(FactoryGap, match="typed Formula"):
        (
            FunctionContract.builder(
                symbol="module::dict::callable",
                out_binding="out",
                out_sort=Int(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .post({"kind": "atomic"})
            .build()
        )


def test_refusal_record_has_no_formula_and_fact_plus_refusal_is_unconstructible() -> None:
    pair = RefusalRecord.verdict_witnesses()
    assert _run_witness_case(pair.truthful) == "sat"
    assert pair.lying.expected == "construction-refusal"

    record = RefusalRecord.from_incomplete(
        Incomplete(RuntimeEffect("opaque runtime effect")),
        provenance=_derived_provenance("RefusalRecord"),
    )
    assert record.denotation() is None
    assert record.cid().startswith("blake3-512:")

    with pytest.raises(FactoryGap, match="both formula and refusal"):
        RefusalRecord.from_incomplete(
            Incomplete(RuntimeEffect("opaque runtime effect")),
            provenance=_derived_provenance("RefusalRecord"),
            formula=eq(make_var("call"), num(0)),
        )


def test_function_contract_rejects_wrong_formula_and_declaration_shapes() -> None:
    with pytest.raises(FactoryGap, match="out binding"):
        (
            FunctionContract.builder(
                symbol="module::bad::callable",
                out_binding="result",
                out_sort=Bool(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .post(eq(make_var("out"), bool_const(True)))
            .build()
        )
