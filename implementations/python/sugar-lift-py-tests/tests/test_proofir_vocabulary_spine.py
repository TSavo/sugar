from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory.literal_call_report import euf_call_term, euf_callsite_name
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.ir import (
    Bool,
    Formula,
    Int,
    and_,
    bool_const,
    eq,
    formula_to_value,
    make_var,
    not_,
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
    REGISTERED_PROOFIR_NODE_CLASSES,
    RefusalRecord,
    Stated,
    canonical_euf_callsite_name,
    merge_equality_facts,
)


ROOT = Path(__file__).resolve().parents[4]
RUST_WORKSPACE = ROOT / "implementations" / "rust"
SMT_LIB_DIALECT = "smt-lib-v2.6"


@dataclass(frozen=True)
class _SolverCase:
    formulas: tuple[Formula, ...]


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
    if not case.formulas:
        return "sat"
    # The compiler's production contract is proof-oriented: it emits
    # `(assert (not F))` so `unsat` means an obligation is discharged. The
    # witness harness asks a model-existence question over all formulas, so
    # feed it `not(and(formulas))`; the production compiler's negation then
    # yields exactly the asserted conjunction we want z3 to check.
    compiled = _compile_formula_with_smt_lib(not_(and_(list(case.formulas))))
    smt = f"{compiled['preamble']}{compiled['body']}"
    completed = subprocess.run(
        ["z3", "-in"],
        input=smt,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.splitlines()[0]


def _compile_formula_with_smt_lib(formula: Formula) -> dict[str, Any]:
    ir_json = json.loads(encode_jcs(formula_to_value(formula)))
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sugar.ir.handshake",
            "params": {
                "sugar_version": "proofir-vocabulary-test",
                "protocol_version": "sugar-ir-compiler/1",
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sugar.ir.compile",
            "params": {
                "ir_json": ir_json,
                "target_dialect": SMT_LIB_DIALECT,
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "sugar.ir.shutdown",
            "params": {},
        },
    ]
    completed = subprocess.run(
        [
            "cargo",
            "run",
            "--locked",
            "-p",
            "sugar-ir-compiler-smt-lib",
            "--bin",
            "sugar-ir-smt-lib",
            "--quiet",
            "--",
        ],
        cwd=RUST_WORKSPACE,
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    assert len(responses) == 3, completed.stdout
    compile_response = responses[1]
    if "error" in compile_response:
        raise AssertionError(
            f"sugar-ir-smt-lib refused witness formula: {compile_response['error']}"
        )
    result = compile_response.get("result")
    assert isinstance(result, dict), compile_response
    return result


def _run_witness_case(case) -> str:
    if case.expected == "construction-refusal":
        assert case.construct is not None
        with pytest.raises(FactoryGap):
            case.construct()
        return "construction-refusal"
    if case.construct is not None:
        constructed = case.construct()
        if isinstance(constructed, RefusalRecord):
            assert constructed.denotation() is None
    return _z3_status(_SolverCase(case.formulas))


def test_witness_harness_uses_real_smt_lib_compiler() -> None:
    compiled = _compile_formula_with_smt_lib(eq(make_var("x"), num(1)))

    assert "(declare-const x Int)" in compiled["preamble"]
    assert "(check-sat)" in compiled["body"]


@pytest.mark.parametrize("node_class", REGISTERED_PROOFIR_NODE_CLASSES)
def test_registered_proofir_witnesses_are_solver_checked(node_class) -> None:
    pair = node_class.verdict_witnesses()

    assert _run_witness_case(pair.truthful) == pair.truthful.expected
    assert _run_witness_case(pair.lying) == pair.lying.expected


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


def test_equality_fact_semantic_merge_collapses_stated_and_derived_warrants() -> None:
    call_term = euf_call_term("h", [num(5)])
    key = canonical_euf_callsite_name(call_term)
    stated = EqualityFact(
        euf_key=key,
        call_term=call_term,
        rhs_term=num(6),
        provenance=_stated_provenance("EqualityFact"),
    )
    derived = EqualityFact(
        euf_key=key,
        call_term=call_term,
        rhs_term=num(6),
        provenance=_derived_provenance("EqualityFact"),
    )

    assert stated.cid() != derived.cid()
    assert stated.semantic_cid() == derived.semantic_cid()
    merged = merge_equality_facts(stated, derived)

    assert merged.semantic_cid() == stated.semantic_cid()
    assert len(merged.provenance().warrants) == 2
    assert merge_equality_facts(stated, stated) == stated
    assert merge_equality_facts(merged, stated) == merged


def test_equality_fact_semantic_merge_refuses_lying_pair() -> None:
    call_term = euf_call_term("h", [])
    key = canonical_euf_callsite_name(call_term)
    stated_lie = EqualityFact(
        euf_key=key,
        call_term=call_term,
        rhs_term=num(7),
        provenance=_stated_provenance("EqualityFact"),
    )
    derived_truth = EqualityFact(
        euf_key=key,
        call_term=call_term,
        rhs_term=num(6),
        provenance=_derived_provenance("EqualityFact"),
    )

    assert stated_lie.semantic_cid() != derived_truth.semantic_cid()
    with pytest.raises(FactoryGap, match="semantic_cid"):
        merge_equality_facts(stated_lie, derived_truth)
    assert _z3_status(
        _SolverCase((stated_lie.denotation(), derived_truth.denotation()))
    ) == "unsat"


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
